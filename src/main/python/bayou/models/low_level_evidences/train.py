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

from __future__ import print_function
import numpy as np
import tensorflow as tf

import argparse
import time
import os
import sys
import json
import textwrap

from bayou.models.low_level_evidences.data_reader import Reader
from bayou.models.low_level_evidences.model import Model
from bayou.models.low_level_evidences.utils import read_config, dump_config, get_var_list, static_plot


HELP = """\
Config options should be given as a JSON file (see config.json for example):
{                                         |
    "model": "lle"                        | The implementation id of this model (do not change)
    "latent_size": 32,                    | Latent dimensionality
    "batch_size": 50,                     | Minibatch size
    "num_epochs": 100,                    | Number of training epochs
    "learning_rate": 0.02,                | Learning rate
    "print_step": 1,                      | Print training output every given steps
    "evidence": [                         | Provide each evidence type in this list
        {                                 |
            "name": "apicalls",           | Name of evidence ("apicalls")
            "units": 64,                  | Size of the encoder hidden state
            "num_layers": 3               | Number of densely connected layers
            "tile": 1                     | Repeat the encoding n times (to boost its signal)
        },                                |
        {                                 |
            "name": "types",              | Name of evidence ("types")
            "units": 32,                  | Size of the encoder hidden state
            "num_layers": 3               | Number of densely connected layers
            "tile": 1                     | Repeat the encoding n times (to boost its signal)
        },                                |
        {                                 |
            "name": "keywords",           | Name of evidence ("keywords")
            "units": 64,                  | Size of the encoder hidden state
            "num_layers": 3               | Number of densely connected layers
            "tile": 1                     | Repeat the encoding n times (to boost its signal)
        }                                 |
    ],                                    |
    "decoder": {                          | Provide parameters for the decoder here
        "units": 256,                     | Size of the decoder hidden state
        "num_layers": 3,                  | Number of layers in the decoder
        "max_ast_depth": 32               | Maximum depth of the AST (length of the longest path)
    }
    "reverse_encoder": {
        "units": 256,
        "num_layers": 3,
        "max_ast_depth": 32
    }                                   |
}                                         |
"""
#%%

def train(clargs):
    config_file = clargs.config if clargs.continue_from is None \
                                else os.path.join(clargs.continue_from, 'config.json')

    with open(config_file) as f:
        config = read_config(json.load(f), chars_vocab=clargs.continue_from)
    reader = Reader(clargs, config)

    jsconfig = dump_config(config)
    # print(clargs)
    # print(json.dumps(jsconfig, indent=2))

    with open(os.path.join(clargs.save, 'config.json'), 'w') as f:
        json.dump(jsconfig, fp=f, indent=2)

    model = Model(config, infer=False, bayou_mode = True, full_model_train = False )
    # merged_summary = tf.summary.merge_all()


    with tf.Session(config=tf.ConfigProto(log_device_placement=True)) as sess:
        writer = tf.summary.FileWriter(clargs.save)
        writer.add_graph(sess.graph)
        tf.global_variables_initializer().run()

        tf.train.write_graph(sess.graph_def, clargs.save, 'model.pbtxt')
        tf.train.write_graph(sess.graph_def, clargs.save, 'model.pb', as_text=False)
        saver = tf.train.Saver(tf.global_variables(), max_to_keep=3)

        # restore model
        if clargs.continue_from is not None:
            bayou_vars = get_var_list()['bayou_vars']
            old_saver = tf.train.Saver(bayou_vars, max_to_keep=None)
            ckpt = tf.train.get_checkpoint_state(clargs.continue_from)
            old_saver.restore(sess, ckpt.model_checkpoint_path)

        # training
        epocLoss , epocGenL , epocKlLoss = [], [], []
        for i in range(config.num_epochs):
            reader.reset_batches()
            avg_loss, avg_gen_loss, avg_KL_loss = 0.,0.,0.
            for b in range(config.num_batches):
                start = time.time()
                # setup the feed dict
                prog_ids, ev_data, n, e, y, _ = reader.next_batch()
                feed = {model.targets: y}
                for j, ev in enumerate(config.evidence):
                    feed[model.encoder.inputs[j].name] = ev_data[j]
                for j in range(config.decoder.max_ast_depth):
                    feed[model.decoder.nodes[j].name] = n[j]
                    feed[model.decoder.edges[j].name] = e[j]
                for j in range(config.reverse_encoder.max_ast_depth):
                    feed[model.reverse_encoder.nodes[j].name] = n[config.reverse_encoder.max_ast_depth - 1 - j]
                    feed[model.reverse_encoder.edges[j].name] = e[config.reverse_encoder.max_ast_depth - 1 - j]

                # run the optimizer
                loss, gen_loss, KL_loss, E_mean, RE_mean, E_covar, RE_covar, _ \
                    = sess.run([model.loss, model.gen_loss, model.KL_loss,
                                model.encoder.psi_mean, model.reverse_encoder.psi_mean,
                                model.encoder.psi_covariance, model.reverse_encoder.psi_covariance,
                                model.train_op], feed)

                # s = sess.run(merged_summary, feed)
                # writer.add_summary(s,i)

                end = time.time()
                avg_loss += np.mean(loss)
                avg_gen_loss += np.mean(gen_loss)
                avg_KL_loss += np.mean(KL_loss)


                step = (i+1) * config.num_batches + b
                if step % config.print_step == 0:
                    print('{}/{} (epoch {}) '
                          'loss: {:.3f}, gen_loss: {:.3f}, KL_loss: {:.3f}, \n\t\t E_mean: {:.3f}, RE_mean: {:.3f}, E_covar: {:.3f}, RE_covar: {:.3f}'.format
                          (step, config.num_epochs * config.num_batches, i + 1 ,
                           (avg_loss)/(b+1), (avg_gen_loss)/(b+1), (avg_KL_loss)/(b+1),
                           np.mean(E_mean), np.mean(RE_mean), np.mean(E_covar),
                           np.mean(RE_covar)))

            epocLoss.append(avg_loss / config.num_batches), epocGenL.append(avg_gen_loss / config.num_batches), epocKlLoss.append(avg_KL_loss / config.num_batches)
            if (i+1) % config.checkpoint_step == 0:
                checkpoint_dir = os.path.join(clargs.save, 'model{}.ckpt'.format(i+1))
                saver.save(sess, checkpoint_dir)
                print('Model checkpointed: {}. Average for epoch , '
                      'loss: {:.3f}'.format
                      (checkpoint_dir, avg_loss / config.num_batches))
        #static_plot(epocLoss , epocGenL , epocKlLoss)


#%%
if __name__ == '__main__':
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                     description=textwrap.dedent(HELP))
    parser.add_argument('input_file', type=str, nargs=1,
                        help='input data file')
    parser.add_argument('--python_recursion_limit', type=int, default=10000,
                        help='set recursion limit for the Python interpreter')
    parser.add_argument('--save', type=str, default='save',
                        help='checkpoint model during training here')
    parser.add_argument('--config', type=str, default=None,
                        help='config file (see description above for help)')
    parser.add_argument('--continue_from', type=str, default=None,
                        help='ignore config options and continue training model checkpointed here')
    #clargs = parser.parse_args()
    clargs = parser.parse_args(
     #['--continue_from', 'save',
     ['--config','config.json',
     # '..\..\..\..\..\..\data\DATA-training-top.json'])
     #'/home/rm38/Research/Bayou_Code_Search/Corpus/DATA-training-expanded-biased-TOP.json'])
     # '/home/ubuntu/Corpus/DATA-training-expanded-biased.json'])
     '/home/ubuntu/DATA-Licensed-sorrEv.json'])
    sys.setrecursionlimit(clargs.python_recursion_limit)
    if clargs.config and clargs.continue_from:
        parser.error('Do not provide --config if you are continuing from checkpointed model')
    if not clargs.config and not clargs.continue_from:
        parser.error('Provide at least one option: --config or --continue_from')
    train(clargs)
