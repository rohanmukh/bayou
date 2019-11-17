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
import tensorflow as tf
import numpy as np
from copy import deepcopy, copy

import os
import pickle
import json

from bayou.models.low_level_evidences.architecture import BayesianEncoder, BayesianDecoder
from bayou.models.low_level_evidences.node import CHILD_EDGE, SIBLING_EDGE, Node
from bayou.models.low_level_evidences.utils import read_config

MAX_GEN_UNTIL_STOP = 20
MAX_AST_DEPTH = 5


class TooLongPathError(Exception):
    pass


class IncompletePathError(Exception):
    pass


class InvalidSketchError(Exception):
    pass


class Candidate():
    def __init__(self,initial_state):
        self.tree_currNode = Node("DSubTree")
        self.head = self.tree_currNode

        self.last_item = self.tree_currNode.val
        self.last_edge = SIBLING_EDGE
        self.branch_stack = []

        self.length = 1
        self.log_probabilty = -np.inf
        self.state = initial_state

        self.rolling = True



class BayesianPredictor(object):

    def __init__(self, save, config):
        self.sess  = tf.InteractiveSession()

        self.config = config
        config.decoder.max_ast_depth = 1
        # load the saved config
        self.inputs = [ev.placeholder(config) for ev in config.evidence]
        ev_data = self.inputs

        self.nodes = tf.placeholder(tf.int32, shape=(config.batch_size,config.decoder.max_ast_depth))
        self.edges = tf.placeholder(tf.bool, shape=(config.batch_size, config.decoder.max_ast_depth))
        self.targets = tf.placeholder(tf.int32, shape=(config.batch_size, config.decoder.max_ast_depth))

        ev_data = self.inputs[:-1]
        surr_input = self.inputs[-1][:-1]
        surr_input_fp = self.inputs[-1][-1]


        nodes = tf.transpose(self.nodes)
        edges = tf.transpose(self.edges)

        with tf.variable_scope('Embedding'):
            emb = tf.get_variable('emb', [config.decoder.vocab_size, config.decoder.units])
        
        with tf.variable_scope("Encoder"):
            self.encoder = BayesianEncoder(config, ev_data, surr_input, surr_input_fp, infer=True)
            samples_1 = tf.random_normal([config.batch_size, config.latent_size], mean=0., stddev=1., dtype=tf.float32)
            self.psi_encoder = self.encoder.psi_mean + tf.sqrt(self.encoder.psi_covariance) * samples_1

        # setup the decoder with psi as the initial state
        with tf.variable_scope("Decoder"):

            lift_w = tf.get_variable('lift_w', [config.latent_size, config.decoder.units])
            lift_b = tf.get_variable('lift_b', [config.decoder.units])


            self.initial_state = tf.nn.xw_plus_b(self.psi_encoder, lift_w, lift_b, name="Initial_State")
            self.decoder = BayesianDecoder(config, emb, self.initial_state, nodes, edges)

        with tf.name_scope("Loss"):
            output = tf.reshape(tf.concat(self.decoder.outputs, 1),
                                [-1, self.decoder.cell1.output_size])
            logits = tf.matmul(output, self.decoder.projection_w) + self.decoder.projection_b
            self.ln_probs = tf.nn.log_softmax(logits)
            self.idx = tf.multinomial(logits, 1)

            self.top_k_values, self.top_k_indices = tf.nn.top_k(self.ln_probs, k=config.batch_size)


        # restore the saved model
        tf.global_variables_initializer().run()
        saver = tf.train.Saver(tf.global_variables())
        ckpt = tf.train.get_checkpoint_state(save)
        saver.restore(self.sess, ckpt.model_checkpoint_path)



    def infer(self, evidences):
        """
        Returns an ordered (by probability) list of ASTs from the model, given evidences, using beam search
        :param evidences: the input evidences
        :param num_psi_samples: number of samples of the intent, averaged before AST construction
        :param beam_width: width of the beam search
        :return: list of ASTs ordered by their probabilities
        """
        asts = self.get_jsons_from_beam_search(evidences, self.config.batch_size)

        return asts



    def get_state(self, evidences, num_psi_samples=1000):
        # get the contrib from evidence to the initial state
        #rdp = [ev.read_data_point(evidences, infer=True) for ev in self.config.evidence]
        #inputs = [ev.wrangle([ev_rdp for k in range(self.config.batch_size)]) for ev, ev_rdp in zip(self.config.evidence, rdp)]
       
        inputs = self.wrange_inputs(evidences)
        
        feed = {}
        for j, _ in enumerate(self.config.evidence[:-1]):
            feed[self.inputs[j].name] = inputs[j]

        for j, _ in enumerate(self.config.evidence[-1].internal_evidences[:-1]):
            feed[self.inputs[-1][j].name] = inputs[-1][j]

        for j in range(2): #len(self.config.evidence[-1].internal_evidences[-1])):
            feed[self.inputs[-1][-1][j].name] = inputs[-1][-1][j]

        #feed = {}
        #for j, ev in enumerate(self.config.evidence):
        #    feed[self.inputs[j].name] = inputs[j]

        psis = []
        for i in range(num_psi_samples):
            psi = self.sess.run(self.psi_encoder, feed)
            psis.append(psi)
        psi = np.mean(psis, axis=0)

        feed = {self.psi_encoder:psi}
        state = self.sess.run(self.initial_state, feed)

        return state


    def wrange_inputs(self, program):

        rdp = [ev.read_data_point(program, infer=True) for ev in self.config.evidence]

        config = self.config
        raw_evidences = [rdp for j in range(self.config.batch_size)]
        raw_evidences = [[raw_evidence[i] for raw_evidence in raw_evidences] for i, ev in enumerate(config.evidence)]
        raw_evidences[-1] = [[raw_evidence[j] for raw_evidence in raw_evidences[-1]] for j in range(len(config.surrounding_evidence))] # for
        raw_evidences[-1][-1] = [[raw_evidence[j] for raw_evidence in raw_evidences[-1][-1]] for j in range(2)] # is
        rdp = raw_evidences

        # inputs = [ev.wrangle([ev_rdp for i in range(self.config.batch_size)]) for ev, ev_rdp in zip(self.config.evidence, rdp)]
        inputs = [ev.wrangle(data) for ev, data in zip(config.evidence, rdp)]

        return inputs


    def beam_search(self, evidences, topK):

        self.config.batch_size = topK

        init_state = self.get_state(evidences)

        candies = [Candidate(init_state[0]) for k in range(topK)]
        candies[0].log_probabilty = -0.0

        i = 0
        while(True):
            # states was batch_size * LSTM_Decoder_state_size
            candies = self.get_next_output_with_fan_out(candies)
            #print([candy.head.breadth_first_search() for candy in candies])
            #print([candy.rolling for candy in candies])

            if self.check_for_all_STOP(candies): # branch_stack and last_item
                break

            i+=1

            if i == MAX_GEN_UNTIL_STOP:
                break


        candies.sort(key=lambda x: x.log_probabilty, reverse=True)

        return candies



    def check_for_all_STOP(self, candies):
        for candy in candies:
            if candy.rolling == True:
                return False

        return True



    def get_next_output_with_fan_out(self, candies):

        topK = len(candies)

        last_item = [[self.config.decoder.vocab[candy.last_item]] for candy in candies]
        last_edge = [[candy.last_edge] for candy in candies]
        states = [candy.state for candy in candies]

        feed = {}
        feed[self.nodes.name] = np.array(last_item, dtype=np.int32)
        feed[self.edges.name] = np.array(last_edge, dtype=np.bool)
        feed[self.initial_state.name] = np.array(states)

        [states, beam_ids, beam_ln_probs, top_idx] = self.sess.run([self.decoder.state, self.top_k_indices, self.top_k_values, self.idx] , feed)

        states = states[0]
        next_nodes = [[self.config.decoder.chars[idx] for idx in beam] for beam in beam_ids]


        # states is still topK * LSTM_Decoder_state_size
        # next_node is topK * topK
        # node_probs in  topK * topK
        # log_probabilty is topK

        log_probabilty = np.array([candy.log_probabilty for candy in candies])
        length = np.array([candy.length for candy in candies])

        for i in range(topK):
            if candies[i].rolling == False:
                length[i] = candies[i].length + 1
            else:
               length[i] = candies[i].length

        for i in range(topK): # denotes the candidate
            for j in range(topK): # denotes the items
                if candies[i].rolling == False and j > 0:
                   beam_ln_probs[i][j] = -np.inf
                elif candies[i].rolling == False and j == 0:
                   beam_ln_probs[i][j] = 0.0

        new_probs = log_probabilty[:,None]  + beam_ln_probs

        len_norm_probs = new_probs #/ np.power(length[:,None], 1.0)

        rows, cols = np.unravel_index(np.argsort(len_norm_probs, axis=None)[::-1], new_probs.shape)
        rows, cols = rows[:topK], cols[:topK]

        # rows mean which of the original candidate was finally selected
        new_candies = []
        for row, col in zip(rows, cols):
            new_candy = deepcopy(candies[row]) #candies[row].copy()
            if new_candy.rolling:
                new_candy.state = states[row]
                new_candy.log_probabilty = new_probs[row][col]
                new_candy.length += 1

                value2add = next_nodes[row][col]
                # print(value2add)


                if new_candy.last_edge == SIBLING_EDGE:
                    new_candy.tree_currNode = new_candy.tree_currNode.addAndProgressSiblingNode(Node(value2add))
                else:
                    new_candy.tree_currNode = new_candy.tree_currNode.addAndProgressChildNode(Node(value2add))


                # before updating the last item lets check for penultimate value
                if new_candy.last_edge == CHILD_EDGE and new_candy.last_item in ['DBranch', 'DExcept', 'DLoop']:
                     new_candy.branch_stack.append(new_candy.tree_currNode)
                     new_candy.last_edge = CHILD_EDGE
                     new_candy.last_item = value2add

                elif value2add in ['DBranch', 'DExcept', 'DLoop']:
                     new_candy.branch_stack.append(new_candy.tree_currNode)
                     new_candy.last_edge = CHILD_EDGE
                     new_candy.last_item = value2add

                elif value2add == 'STOP':
                     if len(new_candy.branch_stack) == 0:
                          new_candy.rolling = False
                     else:
                          new_candy.tree_currNode = new_candy.branch_stack.pop()
                          new_candy.last_item = new_candy.tree_currNode.val
                          new_candy.last_edge = SIBLING_EDGE
                else:
                     new_candy.last_edge = SIBLING_EDGE
                     new_candy.last_item = value2add

            new_candies.append(new_candy)

        return new_candies






    def get_jsons_from_beam_search(self, evidences, topK):

        candidates = self.beam_search(evidences, topK)

        candidates = [candidate for candidate in candidates if candidate.rolling is False]
        # candidates = candidates[0:1]
        # print(candidates[0].head.breadth_first_search())
        candidate_jsons = [self.paths_to_ast(candidate.head, candidate.log_probabilty) for candidate in candidates]
        return candidate_jsons


    def paths_to_ast(self, head_node, log_prob):
        """
        Converts a AST
        :param paths: the set of paths
        :return: the AST
        """
        json_nodes = []
        ast = {'node': 'DSubTree', '_nodes': json_nodes}
        self.expand_all_siblings_till_STOP(json_nodes, head_node.sibling)

        return { 'ast': ast, 'probability':np.exp(log_prob) }


    def expand_all_siblings_till_STOP(self, json_nodes, head_node):
        """
        Updates the given list of AST nodes with those along the path starting from pathidx until STOP is reached.
        If a DBranch, DExcept or DLoop is seen midway when going through the path, recursively updates the respective
        node type.
        :param nodes: the list of AST nodes to update
        :param path: the path
        :param pathidx: index of path at which update should start
        :return: the index at which STOP was encountered if there were no recursive updates, otherwise -1
        """


        while head_node.val != 'STOP':
            node_value = head_node.val
            astnode = {}
            if node_value == 'DBranch':
                astnode['node'] = node_value
                astnode['_cond'] = []
                astnode['_then'] = []
                astnode['_else'] = []
                self.update_DBranch(astnode, head_node.child)
                json_nodes.append(astnode)
            elif node_value == 'DExcept':
                astnode['node'] = node_value
                astnode['_try'] = []
                astnode['_catch'] = []
                self.update_DExcept(astnode, head_node.child)
                json_nodes.append(astnode)
            elif node_value == 'DLoop':
                astnode['node'] = node_value
                astnode['_cond'] = []
                astnode['_body'] = []
                self.update_DLoop(astnode, head_node.child)
                json_nodes.append(astnode)
            else:
                json_nodes.append({'node': 'DAPICall', '_call': node_value})

            head_node = head_node.sibling

        return


    def update_DBranch(self, astnode, branch_node):
        """
        Updates a DBranch AST node with nodes from the path starting at pathidx
        :param astnode: the AST node to update
        :param path: the path
        :param pathidx: index of path at which update should start
        """
        # self.expand_all_siblings_till_STOP(astnode['_cond'], loop_node, pathidx+1)
        if branch_node.val != 'STOP':
            astnode['_cond'] = json_nodes = [{'node': 'DAPICall', '_call': branch_node.val}]
        else:
            astnode['_cond'] = []
        self.expand_all_siblings_till_STOP(astnode['_then'], branch_node.sibling)
        self.expand_all_siblings_till_STOP(astnode['_else'], branch_node.child)
        return

    def update_DExcept(self, astnode, except_node):
        """
        Updates a DExcept AST node with nodes from the path starting at pathidx
        :param astnode: the AST node to update
        :param path: the path
        :param pathidx: index of path at which update should start
        """
        self.expand_all_siblings_till_STOP(astnode['_try'], except_node)
        self.expand_all_siblings_till_STOP(astnode['_catch'], except_node.child)
        return

    def update_DLoop(self, astnode, loop_node):
        """
        Updates a DLoop AST node with nodes from the path starting at pathidx
        :param astnode: the AST node to update
        :param path: the path
        :param pathidx: index of path at which update should start
        """
        self.expand_all_siblings_till_STOP(astnode['_cond'], loop_node)
        self.expand_all_siblings_till_STOP(astnode['_body'], loop_node.child)
        return


    def get_encoder_mean_variance(self, evidences):
        # setup initial states and feed

        rdp = [ev.read_data_point(evidences, infer=True) for ev in self.config.evidence]
        inputs = [ev.wrangle([ev_rdp]) for ev, ev_rdp in zip(self.config.evidence, rdp)]

        feed = {}
        for j, ev in enumerate(self.config.evidence):
            feed[self.inputs[j].name] = inputs[j]


        [  encMean, encCovar ] = self.sess.run([ self.encoder.psi_mean , self.encoder.psi_covariance], feed)

        return encMean[0], encCovar[0]







    def random_search(self, evidences):

        # got the state, to be used subsequently
        state = self.get_state(evidences)
        start_node = Node("DSubTree")
        head, final_state = self.consume_siblings_until_STOP(state, start_node)

        return head.sibling


    def get_prediction(self, node, edge, state):
        feed = {}
        feed[self.nodes.name] = np.array([[self.config.decoder.vocab[node]]], dtype=np.int32)
        feed[self.edges.name] = np.array([[edge]], dtype=np.bool)
        feed[self.initial_state.name] = state

        [state,idx] = self.sess.run([self.decoder.state, self.idx] , feed)
        idx = idx[0][0]
        state = state[0]
        prediction = self.config.decoder.chars[idx]

        return Node(prediction), state



    def consume_siblings_until_STOP(self, state, init_node):
        # all the candidate solutions starting with a DSubTree node
        head = candidate = init_node
        if init_node.val == 'STOP':
            return head

        stack_QUEUE = []

        while True:

            predictionNode, state = self.get_prediction(candidate.val, SIBLING_EDGE, state)
            candidate = candidate.addAndProgressSiblingNode(predictionNode)


            prediction = predictionNode.val
            if prediction == 'DBranch':
                candidate.child, state = self.consume_DBranch(state)
            elif prediction == 'DExcept':
                candidate.child, state = self.consume_DExcept(state)
            elif prediction == 'DLoop':
                candidate.child, state = self.consume_DLoop(state)
            #end of inner while

            elif prediction == 'STOP':
                break

        #END OF WHILE
        return head, state


    def consume_DExcept(self, state):
        catchStartNode, state = self.get_prediction('DExcept', CHILD_EDGE, state)

        tryStartNode, state = self.get_prediction(catchStartNode.val, CHILD_EDGE, state)
        tryBranch , state = self.consume_siblings_until_STOP(state, tryStartNode)

        catchBranch, state = self.consume_siblings_until_STOP(state, catchStartNode)

        catchStartNode.child = tryStartNode

        return tryBranch, state



    def consume_DLoop(self, state):
        loopConditionNode, state = self.get_prediction('DLoop', CHILD_EDGE, state)
        loopStartNode, state = self.get_prediction(loopConditionNode.val, CHILD_EDGE, state)
        loopBranch, state = self.consume_siblings_until_STOP(state, loopStartNode)

        loopConditionNode.sibling = Node('STOP')
        loopConditionNode.child = loopBranch

        return loopConditionNode, state



    def consume_DBranch(self, state):
        ifStatementNode, state = self.get_prediction('DBranch', CHILD_EDGE, state)
        thenBranchStartNode, state = self.get_prediction(ifStatementNode.val, CHILD_EDGE, state)

        thenBranch , state = self.consume_siblings_until_STOP(state, thenBranchStartNode)
        ifElseBranch, state = self.consume_siblings_until_STOP(state, ifStatementNode)


        #
        ifElseBranch.child = thenBranch

        return ifThenBranch, state