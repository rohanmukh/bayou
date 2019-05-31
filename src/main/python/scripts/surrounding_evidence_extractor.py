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
import argparse
import sys
import json
import ijson.backends.yajl2_cffi as ijson
import math
import random
import numpy as np
from itertools import chain
import re
from variable_name_extractor import get_variables
from collections import defaultdict

import sys
sys.path.append('/home/rm38/bayou/src/main/python/')


import bayou.models.low_level_evidences.evidence
from bayou.models.low_level_evidences.utils import gather_calls
import scripts.ast_extractor as ast_extractor

HELP = """Use this script to extract evidences from a raw data file with sequences generated by driver.
You can also filter programs based on number and length of sequences, and control the samples from each program."""


def shorten(call):
    call = re.sub('^\$.*\$', '', call)  # get rid of predicates
    name = call.split('(')[0].split('.')[-1]
    name = name.split('<')[0]  # remove generics from call name
    return name

def extract_evidence(clargs):
    print('Loading data file...')

    f = open(clargs.input_file[0] , 'rb')
    print('Done')

    ''' Program_dict dictionary holds Key values in format
    (Key = File_Name Value = dict(Key = String Method_Name, Value = [String ReturnType, List[String] FormalParam , List[String] Sequences] ))
    '''
    programs_dict = dict()

    with open('train_files.json') as fjs:
        js = json.load(fjs)
        trainProgDict = js['files']

    returnDict = dict()
    FP_Dict = dict()

    types_set = set()

    valid = []
    #This part appends sorrounding evidences
    done = 0
    ignored = 0
    for program in ijson.items(f, 'programs.item'):
        if 'ast' not in program:
            continue


        try:
            file_name = program['file']
            method_name = program['method']

            if (file_name not in trainProgDict):
                continue



            #ast_node_graph, ast_paths = ast_extractor.get_ast_paths(program['ast']['_nodes'])
            #ast_extractor.validate_sketch_paths(program, ast_paths, clargs.max_ast_depth)



            calls = gather_calls(program['ast'])
            apicalls = list(set(chain.from_iterable([bayou.models.low_level_evidences.evidence.APICalls.from_call(call)
                                                     for call in calls])))
            types = list(set(chain.from_iterable([bayou.models.low_level_evidences.evidence.Types.from_call(call)
                                                  for call in calls])))
            keywords = list(set(chain.from_iterable([bayou.models.low_level_evidences.evidence.Keywords.from_call(call)
                                                    for call in calls])))

            header_variable_names, variable_names = get_variables(program['body'])


            sequences = program['sequences']

            sequences = [[shorten(call) for call in json_seq['calls']] for json_seq in sequences]
            # sequences = [[shorten(call) for call in json_seq] for json_seq in sequences]
            sequences.sort(key=len, reverse=True)
            sequences = sequences[0]


            if 'returnType' not in program:
                continue

            if program['returnType'] == 'None':
                program['returnType'] = '__Constructor__'

            returnType = program['returnType']

            if returnType not in returnDict:
                returnDict[returnType] = 1
            else:
                returnDict[returnType] += 1

            formalParam = program['formalParam'] if 'formalParam' in program else []

            javaDoc = program['javaDoc']

            for type in formalParam:
                if type not in FP_Dict:
                    FP_Dict[type] = 1
                else:
                    FP_Dict[type] += 1

            for type in types:
                types_set.add(type)

            if file_name not in programs_dict:
                programs_dict[file_name] = dict()

            if method_name in programs_dict[file_name]:
                print('Hit Found')

            programs_dict[file_name][method_name] = [returnType, method_name, formalParam, header_variable_names, sequences]


        except (ast_extractor.TooLongPathError, ast_extractor.InvalidSketchError) as e:
            ignored += 1

        done += 1
        if done % 100000 == 0:
            print('Extracted evidences of sorrounding features for {} programs'.format(done), end='\n')

    print('')

    print('{:8d} programs/asts in training data'.format(done))
    print('{:8d} programs/asts ignored by given config'.format(ignored))
    print('{:8d} programs/asts to search over'.format(done - ignored))


    train_programs = []

    topRetKeys = dict()
    for w in sorted(returnDict, key=returnDict.get, reverse=True)[:1000]:
        topRetKeys[w] = returnDict[w]

    topFPKeys = dict()
    for w in sorted(FP_Dict, key=FP_Dict.get, reverse=True)[:1000]:
        topFPKeys[w] = FP_Dict[w]

    setOfGoodTypes = types_set | set(topRetKeys.keys()) | set(topFPKeys.keys())

    f.close()
    f = open(clargs.input_file[0] , 'rb')
    done = 0
    for program in ijson.items(f, 'programs.item'):
        if 'ast' not in program:
            continue
        try:

            file_name = program['file']
            method_name = program['method']

            if (file_name not in trainProgDict):
                continue


            ast_node_graph, ast_paths = ast_extractor.get_ast_paths(program['ast']['_nodes'])
            ast_extractor.validate_sketch_paths(program, ast_paths, clargs.max_ast_depth)

            file_name = program['file']
            method_name = program['method']



            sequences = program['sequences']
            sequences = [[shorten(call) for call in json_seq['calls']] for json_seq in sequences]
            # sequences = [[shorten(call) for call in json_seq] for json_seq in sequences]
            sequences.sort(key=len, reverse=True)

            program['sequences'] = sequences[0]

            if 'returnType' not in program:
                continue

            if program['returnType'] == 'None':
                program['returnType'] = '__Constructor__'

            if program['returnType'] not in topRetKeys:
                program['returnType'] = '__UDT__'

            returnType = program['returnType']

            formalParam = program['formalParam'] if 'formalParam' in program else []
            newFP = []
            for type in formalParam:
                if type not in topFPKeys:
                    type = '__UDT__'
                newFP.append(type)




            # if len(sequences) > clargs.max_seqs or (len(sequences) == 1 and len(sequences[0]['calls']) == 1) or \
            #         any([len(sequence['calls']) > clargs.max_seq_length for sequence in sequences]):
            #     continue

            sample = dict(program)



            calls = gather_calls(program['ast'])
            apicalls = list(set(chain.from_iterable([bayou.models.low_level_evidences.evidence.APICalls.from_call(call)
                                                     for call in calls])))
            types = list(set(chain.from_iterable([bayou.models.low_level_evidences.evidence.Types.from_call(call)
                                                  for call in calls])))
            keywords = list(set(chain.from_iterable([bayou.models.low_level_evidences.evidence.Keywords.from_call(call)
                                                    for call in calls])))
            random.shuffle(apicalls)
            random.shuffle(types)
            random.shuffle(keywords)

            sample['apicalls'] = apicalls #programs_dict[file_name][method_name][0]
            sample['types'] = types #programs_dict[file_name][method_name][1]
            sample['keywords'] = keywords #programs_dict[file_name][method_name][2]
            # sample['my_variables'] = programs_dict[file_name][method_name][4]

            sample['returnType'] = returnType
            sample['formalParam'] = newFP

            sample['classTypes'] = set(program['classTypes']) & setOfGoodTypes if 'classTypes' in program else set()

            sample['classTypes'] = list(sample['classTypes'])


            sample['Surrounding_Evidences']=[]

            #(Key = File_Name Value = dict(Key = String Method_Name, Value = [String ReturnType, List[String] FormalParam , List[String] Sequences] ))

            otherMethods = list(programs_dict[file_name].keys())
            random.shuffle(otherMethods)

            maxMethods = 10
            for j, method in enumerate(otherMethods): # Each iterator is a method Name with @linenumber
                # Ignore the current method from list of sorrounding methods
                if method == method_name:
                    continue
                methodEvidences={}
                for choice, evidence in zip(programs_dict[file_name][method],['surr_returnType', 'surr_methodName', 'surr_formalParam', 'surr_header_vars', 'surr_sequences']):
                    if evidence == "surr_returnType":
                        if (choice in setOfGoodTypes):
                            methodEvidences[evidence] = choice
                        else:
                            methodEvidences[evidence] = 'None'
                    elif evidence == "surr_formalParam":
                        methodEvidences[evidence] = []
                        for c in choice:
                            if (c in setOfGoodTypes):
                                methodEvidences[evidence].append(c)
                            else:
                                methodEvidences[evidence].append('None')
                    else:
                        methodEvidences[evidence] = choice



                sample['Surrounding_Evidences'].append(methodEvidences)
                if j == maxMethods:
                    break


            train_programs.append(sample)


        except (ast_extractor.TooLongPathError, ast_extractor.InvalidSketchError) as e:
            ignored += 1

        done += 1
        if done % 100000 == 0:
            print('Extracted evidence [API/Type/Keywords/Sorrounding Evidences] for {} programs'.format(done), end='\n')

    random.shuffle(train_programs)


    print('\nWriting to {}...'.format(clargs.output_file[0]), end='')
    outFile = clargs.output_file[0]
    outFile = outFile.split(".")[0]

    with open(outFile + "_train.json", 'w') as f:
        json.dump({'programs': train_programs}, fp=f, indent=2)


    print('done')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                     description=HELP)
    parser.add_argument('input_file', type=str, nargs=1,
                        help='input data file')
    parser.add_argument('output_file', type=str, nargs=1,
                        help='output data file')
    parser.add_argument('--python_recursion_limit', type=int, default=10000,
                        help='set recursion limit for the Python interpreter')
    parser.add_argument('--max_ast_depth', type=int, default=32,
                        help='max ast depth for out program ')


    clargs = parser.parse_args()
    sys.setrecursionlimit(clargs.python_recursion_limit)
    extract_evidence(clargs)
