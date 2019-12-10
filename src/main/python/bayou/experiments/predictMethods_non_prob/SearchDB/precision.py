from bayou.experiments.predictMethods_non_prob.SearchDB.parallelReadJSON import parallelReadJSON
from bayou.experiments.predictMethods_non_prob.SearchDB.searchFromDB import searchFromDB
from bayou.experiments.predictMethods_non_prob.SearchDB.Embedding import Embedding_iterator_WBatch

import numpy as np
import simplejson as json
from utils import *

if __name__=="__main__":

    numThreads = 30#0
    batch_size = 5
    minJSONs = 1
    maxJSONs = 278 #259
    dimension = 256
    topK = 10

    JSONReader = parallelReadJSON('/home/ubuntu/DATABASE/Non_Prob_Indexed_Data/', numThreads=numThreads, dimension=dimension, batch_size=batch_size, minJSONs=minJSONs , maxJSONs=maxJSONs)
    listOfColDB = JSONReader.readAllJSONs()

    # dicts coming from outside
    print("Loading API Dictionary")
    dict_api_calls = get_api_dict()
    print("Loading AST Dictionary")
    dict_ast = get_ast_dict()
    print("Loading Seq Dictionary")
    dict_seq = get_sequence_dict()

    print ("Initiate Scanner")
    scanner = searchFromDB(listOfColDB, topK, batch_size)
    hit_points = [1,2,3,4,5,6,7,8,9,10]

    for expNumber in [0,1,2,3,4,5,6]:
        print ("Load Embedding for ExpNumber :: "  +  str(expNumber) )
        embIt = Embedding_iterator_WBatch('../log_non_prob/expNumber_'+ str(expNumber) +'/EmbeddedProgramList.json', batch_size, dimension)

        # for first hit
        hit_counts_first_hit_total_body = np.zeros(len(hit_points))
        hit_counts_first_hit_total_ast = np.zeros(len(hit_points))
        hit_counts_first_hit_total_seq = np.zeros(len(hit_points))
        hit_counts_first_hit_total_api = np.zeros(len(hit_points))
        
        mrr_total_body = 0
        mrr_total_ast = 0
        mrr_total_seq = 0
        mrr_total_api = 0
        firstHitRankTotalBody = 0
        firstHitRankTotalAst = 0
        firstHitRankTotalSeq = 0
        firstHitRankTotalApi = 0

        count = 0

        # for precision
        hit_count_jaccard_api_total = np.zeros(len(hit_points))
        hit_counts_exact_match_total = np.zeros(len(hit_points))
        hit_counts_ast_total = np.zeros(len(hit_points))
        hit_counts_seq_total = np.zeros(len(hit_points))

        #for distance
        api_jaccard_dist_total = np.zeros(len(hit_points))
        seq_jaccard_dist_total = np.zeros(len(hit_points))

        # for storage
        JSONList=[]

        for kkk, embedding in enumerate(embIt.embList):
            topKProgsBatch = scanner.searchAndTopKParallel(embedding, numThreads = numThreads)

            for batch_id , topKProgs in enumerate(topKProgsBatch):
                desiredBody, desireAPIcalls, desireSeq, desireAST = get_your_desires( embedding.js[batch_id] )

                # for first hit
                firstHitRankBody = topK #+ 1
                firstHitRankAst = topK #+ 1
                firstHitRankSeq = topK #+ 1
                firstHitRankApi = topK #+ 1

                mrr_body = 1./topK #+ 1
                mrr_ast = 1./topK #+ 1
                mrr_seq = 1./topK #+ 1
                mrr_api = 1./topK #+ 1

                # for precision
                hitPtId = 0
                hit_counts_jaccard_api = np.zeros(len(hit_points))
                hit_counts_exact_match = np.zeros(len(hit_points))
                hit_counts_ast = np.zeros(len(hit_points))
                hit_counts_seq = np.zeros(len(hit_points))

                #for distance
                api_jaccard_dist = np.zeros(len(hit_points))
                seq_jaccard_dist = np.zeros(len(hit_points))

                # for storage
                topProgramDict = embedding.js[batch_id]
                #del topProgramDict['a2'],topProgramDict['b2'],topProgramDict['ProbY'], topProgramDict['ast'], topProgramDict['body'], topProgramDict['testapicalls']
                topProgramDict['desiredProg'] = desiredBody
                topProgramDict['desireAPIcalls'] = desireAPIcalls
                topProgramDict['desireAST'] = desireAST
                programList = list()

                for j, prog in enumerate(topKProgs):

                    key = prog.fileName + "/" + prog.methodName


                    #distance measures
                    ifBodyMatches = exact_match( prog.body , desiredBody )
                    ifASTMatches = exact_match_ast( dict_ast[key] , desireAST )
                    ifSeqMatches = exact_match_sequence( dict_seq[key] , desireSeq )

                    ifAPIMatches = exact_match_api( dict_api_calls[key] , desireAPIcalls )

                    jaccard_distace_api = get_jaccard_distace_api( dict_api_calls[key] , desireAPIcalls )
                    jaccard_distace_sequence = get_jaccard_distace_seq( dict_seq[key] , desireSeq )


                    if ifBodyMatches and j < firstHitRankBody:
                        firstHitRankBody = j
                        mrr_body = 1./(j+1)

                    if ifASTMatches and j < firstHitRankAst:
                        firstHitRankAst = j
                        mrr_ast = 1./(j+1)

                    if ifSeqMatches and j < firstHitRankSeq:
                        firstHitRankSeq = j
                        mrr_seq = 1./(j+1)

                    if ifAPIMatches and j < firstHitRankApi:
                        firstHitRankApi = j
                        mrr_api = 1./(j+1)


                    # for precision
                    hit_counts_jaccard_api[hitPtId] += int(ifAPIMatches)
                    hit_counts_exact_match[hitPtId] += int(ifBodyMatches)
                    hit_counts_ast[hitPtId] += int(ifASTMatches)
                    hit_counts_seq[hitPtId] += int(ifSeqMatches)

                    # for distance
                    api_jaccard_dist[hitPtId] += jaccard_distace_api
                    seq_jaccard_dist[hitPtId] += jaccard_distace_sequence

                    ## For precision calculations
                    if (j+1)  == hit_points[hitPtId]:
                        hitPtId += 1
                        if (hitPtId <10):
                            hit_counts_jaccard_api[hitPtId] += hit_counts_jaccard_api[hitPtId-1]
                            hit_counts_exact_match[hitPtId] += hit_counts_exact_match[hitPtId-1]
                            hit_counts_ast[hitPtId] += hit_counts_ast[hitPtId-1]
                            hit_counts_seq[hitPtId] += hit_counts_seq[hitPtId-1]

                            api_jaccard_dist[hitPtId] += api_jaccard_dist[hitPtId-1]
                            seq_jaccard_dist[hitPtId] += seq_jaccard_dist[hitPtId-1]

                    ## For storage
                    if j < 100:
                        programList.append({j:prog.body})

                #for first hit
                count += 1
                hit_counts_first_hit_total_body, prctg_first_hit_body = rank_statistic(firstHitRankBody, count, hit_counts_first_hit_total_body, hit_points)
                hit_counts_first_hit_total_ast, prctg_first_hit_ast = rank_statistic(firstHitRankAst, count, hit_counts_first_hit_total_ast, hit_points)
                hit_counts_first_hit_total_seq, prctg_first_hit_seq = rank_statistic(firstHitRankSeq, count, hit_counts_first_hit_total_seq, hit_points)
                hit_counts_first_hit_total_api, prctg_first_hit_api = rank_statistic(firstHitRankApi, count, hit_counts_first_hit_total_api, hit_points)


                # for precision
                hit_count_jaccard_api_total += hit_counts_jaccard_api
                hit_counts_exact_match_total += hit_counts_exact_match
                hit_counts_ast_total += hit_counts_ast
                hit_counts_seq_total += hit_counts_seq

                #for distance
                api_jaccard_dist_total += api_jaccard_dist
                seq_jaccard_dist_total += seq_jaccard_dist


                firstHitRankTotalBody += firstHitRankBody + 1
                firstHitRankTotalAst  += firstHitRankAst + 1
                firstHitRankTotalSeq  += firstHitRankSeq + 1
                firstHitRankTotalApi  += firstHitRankApi + 1

                mrr_total_body += mrr_body
                mrr_total_ast += mrr_ast
                mrr_total_seq += mrr_seq
                mrr_total_api += mrr_api


                # for storage
                topProgramDict['first_hit_rank_body'] = firstHitRankBody
                topProgramDict['first_hit_rank_ast'] = firstHitRankAst
                topProgramDict['first_hit_rank_seq'] = firstHitRankSeq
                topProgramDict['first_hit_rank_api'] = firstHitRankApi

                topProgramDict['topPrograms'] = programList
                JSONList.append(topProgramDict)

            # for precision
            prctg_jaccard_api = np.zeros_like(hit_count_jaccard_api_total)
            prctg_exact_match = np.zeros_like(hit_counts_exact_match_total)
            prctg_ast = np.zeros_like(hit_counts_ast_total)
            prctg_seq = np.zeros_like(hit_counts_seq_total)

            #for distance
            avg_jaccard_api_dist = np.zeros_like(api_jaccard_dist_total)
            avg_jaccard_seq_dist = np.zeros_like(seq_jaccard_dist_total)


            denom = float(batch_size * (kkk+1))
            # for firstHit
            avg_firstHitRankTotalBody = firstHitRankTotalBody/denom
            avg_firstHitRankTotalAst  = firstHitRankTotalAst/denom
            avg_firstHitRankTotalSeq  = firstHitRankTotalSeq/denom
            avg_firstHitRankTotalApi  = firstHitRankTotalApi/denom

            avg_mrr_total_body = mrr_total_body/denom
            avg_mrr_total_ast = mrr_total_ast/denom
            avg_mrr_total_seq = mrr_total_seq/denom
            avg_mrr_total_api = mrr_total_api/denom


            for i in range(len(hit_points)):
                denom = float(hit_points[i] * batch_size * (kkk+1))
                prctg_jaccard_api[i] = hit_count_jaccard_api_total[i] / denom
                prctg_exact_match[i] = hit_counts_exact_match_total[i] / denom
                prctg_ast[i] = hit_counts_ast_total[i] / denom
                prctg_seq[i] = hit_counts_seq_total[i] / denom

                avg_jaccard_api_dist[i] = api_jaccard_dist_total[i] / denom
                avg_jaccard_seq_dist[i] = seq_jaccard_dist_total[i] / denom


            if (kkk % 19 == 0 and kkk > 0) or (kkk == len(embIt.embList) - 1):
                print("First Hits")
                print('Searched {} Hit_Pts {} :: API cdf  First Hit {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(prctg_first_hit_api, Type='float')))
                print('Searched {} Hit_Pts {} :: Seq cdf  First Hit {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(prctg_first_hit_seq, Type='float')))
                print('Searched {} Hit_Pts {} :: AST cdf  First Hit {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(prctg_first_hit_ast, Type='float')))
                print('Searched {} Hit_Pts {} :: Body cdf First Hit {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(prctg_first_hit_body, Type='float')))

                print("Precision")
                print('Searched {} Hit_Pts {} :: Precsn API Jaccard {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(prctg_jaccard_api, Type='float')))
                print('Searched {} Hit_Pts {} :: Precison Seq Match {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(prctg_seq, Type='float')))
                print('Searched {} Hit_Pts {} :: Precison AST Match {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(prctg_ast, Type='float')))
                print('Searched {} Hit_Pts {} :: Precsn Exact Match {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(prctg_exact_match, Type='float')))

                print("Distance")
                print('Searched {} Hit_Pts {} :: Distance API Jaccard {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(avg_jaccard_api_dist, Type='float')))
                print('Searched {} Hit_Pts {} :: Distance Seq Match {}'.format
                (batch_size * (kkk+1), ListToFormattedString(hit_points, Type='int'), ListToFormattedString(avg_jaccard_seq_dist, Type='float')))

                print("Average FRank Values")
                print('Searched {} :: Average API Frank value {}'.format(batch_size * (kkk+1), avg_firstHitRankTotalApi ))
                print('Searched {} :: Average Seq Frank value {}'.format(batch_size * (kkk+1), avg_firstHitRankTotalSeq ))
                print('Searched {} :: Average AST Frank value {}'.format(batch_size * (kkk+1), avg_firstHitRankTotalAst ))
                print('Searched {} :: Average Exact Frank value {}'.format(batch_size * (kkk+1), avg_firstHitRankTotalBody ))

                print("Average MRR Values")
                print('Searched {} :: Average API MRR value {}'.format(batch_size * (kkk+1), avg_mrr_total_api ))
                print('Searched {} :: Average Seq MRR value {}'.format(batch_size * (kkk+1), avg_mrr_total_seq ))
                print('Searched {} :: Average AST MRR value {}'.format(batch_size * (kkk+1), avg_mrr_total_ast ))
                print('Searched {} :: Average Exact MRR value {}'.format(batch_size * (kkk+1), avg_mrr_total_body ))

                print()
                with open("../log_non_prob" + "/expNumber_" + str(expNumber) + '/L5TopProgramList.json', 'w') as f:
                    json.dump({'topPrograms': JSONList}, fp=f, indent=2)
                break
