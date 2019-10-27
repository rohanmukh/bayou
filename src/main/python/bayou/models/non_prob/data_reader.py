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
import json
import ijson.backends.yajl2_cffi as ijson
import numpy as np
import random
import os
import _pickle as pickle
from collections import Counter
import gc
import copy

from bayou.models.low_level_evidences.utils import gather_calls
from bayou.models.non_prob.utils import dump_config
from bayou.models.low_level_evidences.data_reader import decoderDict
from bayou.models.low_level_evidences.node import Node, get_ast_from_json, CHILD_EDGE, SIBLING_EDGE, TooLongLoopingException, TooLongBranchingException


class TooLongPathError(Exception):
    pass


class InvalidSketchError(Exception):
    pass


class Reader():
    def __init__(self, clargs, config, infer=False, dataIsThere=False):
        self.infer = infer
        self.config = config

        if clargs.continue_from is not None or dataIsThere:
            print('Loading Data')
            with open('data/inputs.npy', 'rb') as f:
                self.inputs = pickle.load(f)
            # with open(, 'rb') as f:
            self.nodes = np.load('data/nodes.npy')
            self.edges = np.load('data/edges.npy')


            #np.random.seed(0)
            #perm = np.random.permutation(len(self.nodes))
            #perm = np.random.permutation(500)
            perm = []
            for i in range(len(self.nodes)//config.batch_size):
                temp_perm = i*config.batch_size + np.random.permutation(config.batch_size)
                perm.extend(temp_perm)


            temp_inputs = copy.deepcopy(self.inputs)

            inputs_negative = [input_[perm] for input_ in temp_inputs[:-1]]
            inputs_negative.append([input_surr[perm] for input_surr in temp_inputs[-1][:-1]])
            inputs_negative[-1].append([input_surr_fp[perm] for input_surr_fp in temp_inputs[-1][-1]])

            self.inputs_negative = inputs_negative

            jsconfig = dump_config(config)
            with open(os.path.join(clargs.save, 'config.json'), 'w') as f:
                json.dump(jsconfig, fp=f, indent=2)

            if infer:
                self.js_programs = []
                with open('data/js_programs.json', 'rb') as f:
                    for program in ijson.items(f, 'programs.item'):
                        self.js_programs.append(program)
            config.num_batches = int(len(self.nodes) / config.batch_size)
            print('Done')

        else:
            random.seed(12)
            # read the raw evidences and targets
            print('Reading data file...')
            raw_evidences, raw_targets, js_programs = self.read_data(clargs.input_file[0], infer, save=clargs.save)

            raw_evidences = [[raw_evidence[i] for raw_evidence in raw_evidences] for i, ev in enumerate(config.evidence)]
            raw_evidences[-1] = [[raw_evidence[j] for raw_evidence in raw_evidences[-1]] for j in range(len(config.surrounding_evidence))] # for
            raw_evidences[-1][-1] = [[raw_evidence[j] for raw_evidence in raw_evidences[-1][-1]] for j in range(2)] # is


            config.num_batches = int(len(raw_targets) / config.batch_size)

            ################################

            assert config.num_batches > 0, 'Not enough data'
            sz = config.num_batches * config.batch_size
            for i in range(len(config.evidence)-1): #-1 to leave surrounding evidences
                raw_evidences[i] = raw_evidences[i][:sz]

            for i in range(len(config.surrounding_evidence)-1): #-1 to leave formal params
                raw_evidences[-1][i] = raw_evidences[-1][i][:sz]


            for j in range(2):
                raw_evidences[-1][-1][j] = raw_evidences[-1][-1][j][:sz]

            raw_targets = raw_targets[:sz]
            js_programs = js_programs[:sz]

            # setup input and target chars/vocab
            # adding the same variables for reverse Encoder
            config.reverse_encoder.vocab, config.reverse_encoder.vocab_size = self.decoder_api_dict.get_call_dict()

            # wrangle the evidences and targets into numpy arrays
            self.inputs = [ev.wrangle(data) for ev, data in zip(config.evidence, raw_evidences)]
            self.nodes = np.zeros((sz, config.reverse_encoder.max_ast_depth), dtype=np.int32)
            self.edges = np.zeros((sz, config.reverse_encoder.max_ast_depth), dtype=np.bool)
            self.targets = np.zeros((sz, config.reverse_encoder.max_ast_depth), dtype=np.int32)

            for i, path in enumerate(raw_targets):
                len_path = min(len(path) , config.reverse_encoder.max_ast_depth)
                mod_path = path[:len_path]

                self.nodes[i, :len_path]   =  [ p[0] for p in mod_path ]
                self.edges[i, :len_path]   =  [ p[1] for p in mod_path ]
                self.targets[i, :len_path] =  [ p[2] for p in mod_path ]

            self.js_programs = js_programs

            # negative_sampling
            perm = []
            for i in range(len(self.nodes)//config.batch_size):
                temp_perm = i*config.batch_size + np.random.permutation(config.batch_size)
                perm.extend(temp_perm)


            temp_inputs = copy.deepcopy(self.inputs)

            inputs_negative = [input_[perm] for input_ in temp_inputs[:-1]]
            inputs_negative.append([input_surr[perm] for input_surr in temp_inputs[-1][:-1]])
            inputs_negative[-1].append([input_surr_fp[perm] for input_surr_fp in temp_inputs[-1][-1]])

            self.inputs_negative = inputs_negative


            print('Done!')
            # del raw_evidences
            # del raw_targets
            # gc.collect()

            print('Saving...')
            with open('data/inputs.npy', 'wb') as f:
                pickle.dump(self.inputs, f, protocol=4) #pickle.HIGHEST_PROTOCOL)
            # with open(', 'wb') as f:
            np.save('data/nodes', self.nodes)
            np.save('data/edges', self.edges)
            np.save('data/targets', self.targets)

            with open('data/js_programs.json', 'w') as f:
                json.dump({'programs': self.js_programs}, fp=f, indent=2)

            jsconfig = dump_config(config)
            with open(os.path.join(clargs.save, 'config.json'), 'w') as f:
                json.dump(jsconfig, fp=f, indent=2)
            with open('data/config.json', 'w') as f:
                json.dump(jsconfig, fp=f, indent=2)

            print("Saved")


    def read_data(self, filename, infer, save=None):

        data_points = []
        done, ignored_for_branch, ignored_for_loop = 0, 0, 0
        self.decoder_api_dict = decoderDict(infer, self.config.reverse_encoder)

        f = open(filename , 'rb')

        for program in ijson.items(f, 'programs.item'):
            if 'ast' not in program:
                continue
            try:
                evidences = [ev.read_data_point(program, infer) for ev in self.config.evidence]
                ast_node_graph = get_ast_from_json(program['ast']['_nodes'])

                ast_node_graph.sibling.check_nested_branch()
                ast_node_graph.sibling.check_nested_loop()

                path = ast_node_graph.depth_first_search()

                parsed_data_array = []
                for i, (curr_node_val, parent_node_id, edge_type) in enumerate(path):
                    curr_node_id = self.decoder_api_dict.get_or_add_node_val_from_callMap(curr_node_val)
                    # now parent id is already evaluated since this is top-down breadth_first_search
                    parent_call = path[parent_node_id][0]
                    parent_call_id = self.decoder_api_dict.get_node_val_from_callMap(parent_call)

                    if i > 0 and not (curr_node_id is None or parent_call_id is None): # I = 0 denotes DSubtree ----sibling---> DSubTree
                        parsed_data_array.append((parent_call_id, edge_type, curr_node_id))

                sample = dict()
                sample['file'] = program['file']
                sample['method'] = program['method']
                sample['body'] = program['body']

                data_points.append((evidences, parsed_data_array, sample))
                done += 1

            except (TooLongLoopingException) as e1:
                ignored_for_loop += 1

            except (TooLongBranchingException) as e2:
                ignored_for_branch += 1

            if done % 100000 == 0:
                print('Extracted data for {} programs'.format(done), end='\n')
                # break

        print('{:8d} programs/asts in training data'.format(done))
        print('{:8d} programs/asts missed in training data for loop'.format(ignored_for_loop))
        print('{:8d} programs/asts missed in training data for branch'.format(ignored_for_branch))


        # randomly shuffle to avoid bias towards initial data points during training
        random.shuffle(data_points)
        evidences, parsed_data_array, js_programs = zip(*data_points) #unzip


        return evidences, parsed_data_array, js_programs
