import tensorflow as tf
import bayou.models.low_level_evidences.predict
import argparse
import sys
import socket
import json
import os

from bayou.experiments.predictMethods_non_prob.SearchDB.parallelReadJSON import parallelReadJSON
from bayou.experiments.predictMethods_non_prob.SearchDB.searchFromDB import searchFromDB
from bayou.experiments.predictMethods_non_prob.SearchDB.Embedding import EmbeddingBatch


# TODO
# We do not support more than 10 qry programs now

class Rev_Encoder_Model:
    def __init__(self, db_location, batch_size=1, topK=10):
        self.numThreads = 30
        self.batch_size = batch_size
        self.minJSONs = 1
        self.maxJSONs = 10
        self.dimension = 256
        self.topK = topK
        self.db_location = db_location
        self.scanner = self.get_database_scanner()
        return

    def get_database_scanner(self):

        JSONReader = parallelReadJSON(self.db_location, numThreads=self.numThreads, dimension=self.dimension, batch_size=self.batch_size, minJSONs=self.minJSONs , maxJSONs=self.maxJSONs)
        listOfColDB = JSONReader.readAllJSONs()
        scanner = searchFromDB(listOfColDB, self.topK, self.batch_size)
        return scanner


    def get_results(self, all_qry_progs):

        embIt_json = []
        for ev_psi in all_qry_progs['psis_encs']:
            embIt_json.append({'ev_psi':ev_psi})

        embIt_batch = EmbeddingBatch(embIt_json, self.batch_size, 256)
        topKProgsBatch = self.scanner.searchAndTopKParallel(embIt_batch, numThreads = self.numThreads)
        #print(topKProgsBatch)

        return [[(prog.body, prog) for prog in topKProgs[:self.topK]] for topKProgs in topKProgsBatch]



    def dump_result(self, all_qry_progs):
        reverse_encoder_batch_top_progs = self.get_results(all_qry_progs)
        num_qrys = len(all_qry_progs['psis_encs'])
        for j, rev_encoder_top_progs in enumerate(reverse_encoder_batch_top_progs):
            if not j < num_qrys: # batch_size is fixed at 10
               break
            for i, top_prog in enumerate(rev_encoder_top_progs):
               #print('Rank ::' +  str(i))
               #print('Prob ::' + str(top_prog[1]))
               #print(top_prog[0])
               _folder = 'log/qry_' + str(j)
               if not os.path.exists(_folder):
                    os.makedirs(_folder)
               with open(_folder + '/program'+str(i)+'.java','w') as f:
                    f.write(top_prog[0])
            print("=====================================")

        os.remove('log/output.json')





def socket_server(rev_encoder):
	serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	serv.bind((socket.gethostname(), 5001))
	serv.listen(5)
	print('Server Starting!')
	while True:
	     conn, addr = serv.accept()
	     print('Client Accepted')
	     #from_client = ''
	     while True:
	         data = conn.recv(1000000)
	         data.decode()
	         if not data: break
	         #from_client += data

	         results = rev_encoder.dump_result(json.loads(data))
	         send_data='done'
	         conn.send(send_data.encode())
	conn.close()
	print ('client disconnected')





if __name__ == "__main__":
    #%%
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--python_recursion_limit', type=int, default=10000,
    help='set recursion limit for the Python interpreter')
    parser.add_argument('--db_location', type=str, default='/home/ubuntu/DATABASE/')


    clargs = parser.parse_args()
    sys.setrecursionlimit(clargs.python_recursion_limit)


    #rev_encoder = Rev_Encoder_Model_2(pred)
    rev_encoder = Rev_Encoder_Model(clargs.db_location, batch_size=10, topK=5)
    #rev_encoder_batch_top_progs = rev_encoder.get_result(eAs, eBs)

    socket_server(rev_encoder)

