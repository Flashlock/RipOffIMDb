#!/usr/bin/python

import whoosh, csv, json, os.path, sys, nltk
import pandas as pd
import nltk
from nltk.corpus import stopwords
from flask import Flask, request, jsonify
from flask_cors import CORS
from whoosh.index import create_in, open_dir, exists_in, Index
from whoosh.fields import *
from whoosh.qparser import QueryParser, MultifieldParser, query
from whoosh.query import NumericRange, FuzzyTerm
from whoosh import qparser
from fuzzy_search.BKTree import BKTree

# Download corpus if missing
try:
    nltk.data.find("corpora/stopwords")
except LookupError:
    nltk.download("stopwords")

app = Flask(__name__,
            template_folder='./frontend/src')
CORS(app)

fuzzy_tree = None

csv_file = 'database/database_master.csv'

to_rebuild = False

stop_words = set(stopwords.words('english'))

def createBKTree():
    vocab = []
    with open('database/vocabulary.csv', encoding='utf-8', newline='') as csvfile:
        reader = csv.reader(csvfile, delimiter=',')
        for line in reader:
            vocab.append(line[0])

    return BKTree(vocab, 0)

@app.before_first_request
def before_first_request_func():
    global theWhooshSearch
    theWhooshSearch = WhooshSearch()
    print('Building database')
    theWhooshSearch.index()
    print('Database completed')
    global fuzzy_tree

    if not fuzzy_tree:
        print('Building fuzzy search')
        if(to_rebuild):
            fuzzy_tree = createBKTree()
        else: 
            fuzzy_tree = BKTree(decode_file_path='fuzzy_search/encoded_tree.csv')
        print('Fuzzy search completed')

# homepage route
@app.route('/', methods=['GET', 'POST'])
def results():
    """ route for fetch request from front-end
    Advanced search and basic allow for either custom fuzzy search or whoosh included fuzzy search
    Pagination is performed manually on advanced search to allow for filters to be added
    :var searchType: One of two values: basic or advanced to specify the type of search executed - required field
    :var keywordQuery: movie title for advanced search or query for basic search - required field
    :var fuzzySearch: boolean of if fuzzy search is used within basic search - optional field
    :var actor: advanced search field - optional field
    :var production_company: advanced search field - optional field
    :var genre: advanced search field - optional field
    :var runTime: integer passed as a range of movie run times - optional field
    """
    length = 0
    hasNext = False
    nextPageNumber = None
    fuzzy_terms = []
    r = []

    theWhooshSearch = WhooshSearch()
    theWhooshSearch.index()

    if request.method == 'POST':
        data = request.form
    else:
        data = request.args

    searchType = data.get('searchType')
    keywordQuery = data.get('keywordQuery')
    fuzzySearch = data.get('fuzzySearch')
    page = int(data.get('pageNumber'))

    if keywordQuery:
        keywordQuery = removeStop(keywordQuery)

        if searchType == 'advanced':
            actor = data.get('actor')
            production_company = data.get('production')
            director = data.get('director')
            genre = data.get('genre')
            runTime = data.get('runtime')
            if fuzzySearch == 'True' or fuzzySearch == 'true':
                whooshFuzzy = data.get('whoosh')
                if whooshFuzzy == 'True' or whooshFuzzy == 'true':
                    # Whoosh Advanced Fuzzy Search
                    r, length = theWhooshSearch.advancedSearch(
                        keywordQuery, actor, production_company, director, genre, runTime, whooshFuzzy, page)
                else:
                    # BK Tree Advanced Search
                    keywordQuery = keywordQuery.split()
                    for word in keywordQuery:
                        fuzzy_terms += fuzzy_tree.autocorrect(word, 1)
                    for term in fuzzy_terms:
                        tempResult, tempLength = theWhooshSearch.advancedSearch(
                            term[0], actor, production_company, director, genre, runTime, False, pageNumber=-1)
                        r += tempResult
                        length += tempLength
                    r = r[page * 10 - 10:page * 10]
            else:
                # Regular Advanced Search
                r, length = theWhooshSearch.advancedSearch(
                    keywordQuery, actor, production_company, director, genre, runTime, False, page)
        else:
            if fuzzySearch == 'True' or fuzzySearch == 'true':
                whooshFuzzy = data.get('whoosh')
                if whooshFuzzy == 'True' or whooshFuzzy == 'true':
                    r, length = theWhooshSearch.basicSearch(
                        keywordQuery, whooshFuzzy, page)
                else:
                    keywordQuery = keywordQuery.split()
                    for word in keywordQuery:
                        fuzzy_terms += fuzzy_tree.autocorrect(word, 1)
                    for term in fuzzy_terms:
                        tempResult, tempLength = theWhooshSearch.basicSearch(
                            term[0], False, pageNumber=-1)
                        r += tempResult
                        length += tempLength
                    r = r[page * 10 - 10:page * 10]
            else:
                r, length = theWhooshSearch.basicSearch(
                    keywordQuery, False, page)

    # Check if there are new pages
    if nextPage(length, page):
        nextPageNumber = page + 1
    previous = page - 1
    returnResults = {'nextPage': nextPageNumber,
                     'prevPage': previous, 'results': r}
    return jsonify(returnResults)


def nextPage(length, pageNumber):
    return (int(length) - int(pageNumber) * 10) > 1

def removeStop(queryArray):
    query = queryArray.split()
    phrase = ''
    for word in query:
            if word not in stop_words:
                phrase += word + ' '
    return phrase


class WhooshSearch(object):
    def __init__(self):
        super(WhooshSearch, self).__init__()

    def basicSearch(self, query_entered, whooshFuzzy, pageNumber):
        """ Basic search on the whoosh database, query is searched on the title and actors field
        """
        returnables = []
        with self.indexer.searcher() as search:

            if whooshFuzzy == 'True' or whooshFuzzy == 'true':
                query = MultifieldParser(
                    ['Title', 'Actors'], schema=self.indexer.schema, termclass=FuzzyTerm)
            else:
                query = MultifieldParser(
                    ['Title', 'Actors'], schema=self.indexer.schema)

            query = query.parse(query_entered)
            
            if pageNumber == -1:
                results = search.search(query, limit=None)
            else:
                results = search.search_page(query, int(pageNumber))

            for result in results:
                returnables.append({'id': result['id'],
                                    'page_url': result['page_url'],
                                    'image_url': result['image_url'],
                                    'title': result['Title'],
                                    'actors': result['Actors'],
                                    'production': result['Production'],
                                    'director': result['Director'],
                                    'release_date': result['Release_date'],
                                    'genre': result['Genre'],
                                    'awards': result['Awards'],
                                    'critics': result['Critic_Score'],
                                    'runtime': result['RunTime']})

            return returnables, len(results)

    def query_filter_exists(self, allow_q, new_term):
        """
        query_filter_exists checks if the allowed query filter exists or not. If
        it does, combine the allowed query with the new query term, else return
        the new query term.

        :param allow_q: allowed query
        :type allow_q: Query Term object
        :param new_term: new Query Term object
        :type new_term: Query Term object
        :return: Either the combined query terms, or the new query term object
        :rtype: Query Term object
        """
        if(allow_q is None):
            return new_term
        else:
            return allow_q & new_term

    def advancedSearch(self, query_entered, Actor, Production, Director, Genre, runtime, whooshFuzzy, pageNumber):
        ''' provides filters to search across multiple fields based on user input
            query_entered/title is a required field, all other fields are optional
        '''
        title = query_entered

        returnables = []

        if runtime:
            runtime = runtime.split('-')
        # reset filter before each search
        allow_q = None

        with self.indexer.searcher() as search:

            if whooshFuzzy == 'True' or whooshFuzzy == 'true':
                qp = qparser.QueryParser(
                    'Title', self.indexer.schema, termclass=FuzzyTerm)
            else:
                qp = qparser.QueryParser('Title', self.indexer.schema)

            user_q = qp.parse(title)

            # Begin filtering results based on the given tags
            if Actor != "":
                allow_q = self.query_filter_exists(
                    allow_q, query.Term('Actors', Actor))
            if Director != "":
                allow_q = self.query_filter_exists(
                    allow_q, query.Term('Director', Director))
            if Genre != "":
                allow_q = self.query_filter_exists(
                    allow_q, query.Term('Genre', Genre))
            if Production != "":
                allow_q = self.query_filter_exists(
                    allow_q, query.Term('Production', Production))
            if runtime != None:
                allow_q = self.query_filter_exists(
                    allow_q, query.NumericRange('RunTime', runtime[0], runtime[1]))

            # Begin searching
            if allow_q != None and pageNumber == -1:
                results = search.search(user_q, filter=allow_q, limit=None)
            elif allow_q != None:
                results = search.search_page(
                    user_q, int(pageNumber), filter=allow_q)
            elif pageNumber == -1:
                results = search.search(user_q, limit=None)
            else:
                results = search.search_page(user_q, int(pageNumber))

            # Iterate through results
            for result in results:
                returnables.append(
                    {'id': result['id'],
                     'page_url': result['page_url'],
                     'image_url': result['image_url'],
                     'title': result['Title'],
                     'actors': result['Actors'],
                     'production': result['Production'],
                     'director': result['Director'],
                     'release_date': result['Release_date'],
                     'genre': result['Genre'],
                     'awards': result['Awards'],
                     'critics': result['Critic_Score'],
                     'runtime': result['RunTime']})

            return returnables, len(results)

    def index(self):
        """ Establishes the whoosh database for the movies in our csv file
            Only indexes if a database does not already exist
            All fields of extracted data are indexed for the advanced search
        """
        schema = Schema(id=ID(stored=True),
                        image_url=TEXT(stored=True),
                        page_url=TEXT(stored=True),
                        Title=TEXT(stored=True),
                        Actors=TEXT(stored=True),
                        Production=TEXT(stored=True),
                        Director=TEXT(stored=True),
                        Release_date=TEXT(stored=True),
                        Genre=TEXT(stored=True),
                        Awards=TEXT(stored=True),
                        Critic_Score=TEXT(stored=True),
                        RunTime=NUMERIC(stored=True))

        if not os.path.exists('indexdir'):
            os.mkdir('indexdir')

        if (exists_in('indexdir') != True):
            indexer = create_in('indexdir', schema)
            writer = indexer.writer()

            df = pd.read_csv(csv_file, encoding='iso-8859-1')

            for i in range(len(df)):

                runtime = 0
                if not pd.isnull(df.loc[i, 'Runtime']):
                    runtime = df.loc[i, 'Runtime']

                critic_Score = []
                criticScoreArray = json.loads(df.loc[i, 'Critic_Score'])
                for jsonObj in criticScoreArray:
                    critic_Score.append(
                        jsonObj['Source'] + ': ' + jsonObj['Value'])

                writer.add_document(id=str(df.loc[i, 'id']),
                                    image_url=str(df.loc[i, 'image_url']),
                                    page_url=str(df.loc[i, 'page_url']),
                                    Title=str(df.loc[i, 'Title']),
                                    Actors=str(df.loc[i, 'Actors']),
                                    Production=str(df.loc[i, 'Production']),
                                    Director=str(df.loc[i, 'Director']),
                                    Release_date=str(
                                        df.loc[i, 'Release_date']),
                                    Genre=str(df.loc[i, 'Genre']),
                                    Awards=str(df.loc[i, 'Awards']),
                                    Critic_Score=(critic_Score),
                                    RunTime=int(runtime))
            writer.commit()
            self.indexer = indexer

        else:
            self.indexer = open_dir('indexdir')


if __name__ == '__main__':
    global theWhooshSearch
    # To specify rebuilding the tree 
    if len(sys.argv) > 1 and sys.argv[1].lower() == "build":
        to_rebuild = True
    theWhooshSearch = WhooshSearch()
    theWhooshSearch.index()
    app.before_first_request(before_first_request_func)
    app.run(debug=False)
