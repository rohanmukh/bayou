# Copyright 2017 Rice University
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import tensorflow as tf
from tensorflow.contrib import legacy_seq2seq as seq2seq
import numpy as np

from bayou.models.low_level_evidences.architecture import BayesianEncoder, BayesianDecoder, BayesianReverseEncoder
from bayou.models.low_level_evidences.data_reader import CHILD_EDGE, SIBLING_EDGE


class Model():
    def __init__(self, config, infer=False):
        assert config.model == 'lle', 'Trying to load different model implementation: ' + config.model
        self.config = config
        if infer:
            config.batch_size = 1
            config.decoder.max_ast_depth = 1

        # setup the reverse encoder.
        self.reverse_encoder = BayesianReverseEncoder(config)
        samples = tf.random_normal([config.batch_size, config.latent_size],
                                   mean=0., stddev=1., dtype=tf.float32)
        self.psi = self.reverse_encoder.psi_mean + tf.sqrt(self.reverse_encoder.psi_covariance) * samples

        #setup the encode, however remember that the Encoder is there only for KL-divergence
        # Also note that no samples were generated from it
        self.encoder = BayesianEncoder(config)

        # setup the decoder with psi as the initial state
        lift_w = tf.get_variable('lift_w', [config.latent_size, config.decoder.units])
        lift_b = tf.get_variable('lift_b', [config.decoder.units])
        self.initial_state = tf.nn.xw_plus_b(self.psi, lift_w, lift_b)
        self.decoder = BayesianDecoder(config, initial_state=self.initial_state, infer=infer)

        # get the decoder outputs
        output = tf.reshape(tf.concat(self.decoder.outputs, 1),
                            [-1, self.decoder.cell1.output_size])
        logits = tf.matmul(output, self.decoder.projection_w) + self.decoder.projection_b
        self.probs = tf.nn.softmax(logits)

        # 1. generation loss: log P(X | \Psi)
        self.targets = tf.placeholder(tf.int32, [config.batch_size, config.decoder.max_ast_depth])
        self.gen_loss = seq2seq.sequence_loss([logits], [tf.reshape(self.targets, [-1])],
                                              [tf.ones([config.batch_size * config.decoder.max_ast_depth])])

        # 2. latent loss: negative of the KL-divergence between P(\Psi | f(\Theta)) and P(\Psi)
        #remember, we are minimizing the loss, but derivations were to maximize the lower bound and hence no negative sign
        latent_loss = 0.5 * tf.reduce_sum( tf.log(self.encoder.psi_covariance) - tf.log(self.reverse_encoder.psi_covariance)
                                          - 1 + self.reverse_encoder.psi_covariance / self.encoder.psi_covariance
                                          + tf.square(self.encoder.psi_mean - self.reverse_encoder.psi_mean)/self.encoder.psi_covariance
                                          , axis=1)
        self.latent_loss = latent_loss

        # # 3. evidence loss: log P(f(\theta) | \Psi; \sigma)
        # evidence_loss = [ev.evidence_loss(self.psi, encoding, config) for ev, encoding
        #                  in zip(config.evidence, self.encoder.encodings)]
        # evidence_loss = [tf.reduce_sum(loss, axis=1) for loss in evidence_loss]
        # self.evidence_loss = config.beta * tf.reduce_sum(tf.stack(evidence_loss), axis=0)

        # The optimizer
        self.loss = self.gen_loss + self.latent_loss
        self.train_op = tf.train.AdamOptimizer(config.learning_rate).minimize(self.loss)

        var_params = [np.prod([dim.value for dim in var.get_shape()])
                      for var in tf.trainable_variables()]
        if not infer:
            print('Model parameters: {}'.format(np.sum(var_params)))

    # Last but one function I am not aware of.
    # Qs: Why is this is model anyway?
    def infer_psi(self, sess, evidences):
        # Qs: What is evidences. I believe a JSON with headings as keywords, apicalls etc
        # read and wrangle (with batch_size 1) the data
        inputs = [ev.wrangle([ev.read_data_point(evidences)]) for ev in self.config.evidence]
        # setup initial states and feed
        feed = {}
        for j, ev in enumerate(self.config.evidence):
            # Note that writing .name after every tf variable is a norm
            feed[self.encoder.inputs[j].name] = inputs[j]
        #psi is in model.py only
        psi = sess.run(self.psi, feed)
        return psi

    def infer_ast(self, sess, psi, nodes, edges, cache=None):
        # check cache if provided
        if cache is not None:
            serialized = ','.join(['(' + node + ',' + edge + ')' for node, edge in zip(nodes, edges)])
            if serialized in cache:
                return cache[serialized]

        # use the given psi and get decoder's start state
        state = sess.run(self.initial_state, {self.psi: psi})
        state = [state] * self.config.decoder.num_layers

        # run the decoder for every time step
        for node, edge in zip(nodes, edges):

            assert edge == CHILD_EDGE or edge == SIBLING_EDGE, 'invalid edge: {}'.format(edge)
            n = np.array([self.config.decoder.vocab[node]], dtype=np.int32)
            e = np.array([edge == CHILD_EDGE], dtype=np.bool)

            feed = {self.decoder.nodes[0].name: n,
                    self.decoder.edges[0].name: e}
            for i in range(self.config.decoder.num_layers):
                feed[self.decoder.initial_state[i].name] = state[i]
            [probs, state] = sess.run([self.probs, self.decoder.state], feed)

        dist = probs[0]

        # save in cache if provided
        if cache is not None:
            cache[serialized] = dist

        return dist
