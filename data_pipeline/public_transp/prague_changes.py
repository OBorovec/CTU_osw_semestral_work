import hashlib
from collections import defaultdict
from datetime import datetime

import rdflib
from bs4 import BeautifulSoup
from dateutil import parser
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, XSD

from data_pipeline.common.producer.rss_producer import RSSProducer
from data_pipeline.common.transformer.item_rdf_transformer import ItemToRDFTransformer
from data_pipeline.public_transp import PT_PRAGUE_CHANGES_NAME_SPACE, PT_PRAGUE_CHANGES_URL


class PTPragueChangesCrawler(RSSProducer):
    RSS_URL = PT_PRAGUE_CHANGES_URL
    LUIGI_OUTPUT_FILE = 'PTPragueChangesCrawler'
    NAME = 'PTPragueChangesCrawler'
    META_FILE = 'PTPragueChangesCrawler'


class PTPragueChangesRDF(ItemToRDFTransformer):
    NAME = 'PTPragueChangesRDF'
    NAMESPACE = PT_PRAGUE_CHANGES_NAME_SPACE
    NAMESPACE_PREFIX = 'pragueChanges'
    LUIGI_OUTPUT_FILE = 'PTPragueChangesRDF'

    def requires(self):
        return PTPragueChangesCrawler(self.unique_param)

    def parse_item_to_graph(self, item, g, n):
        # Adding to graph
        id = hashlib.md5(str(item).encode('utf-8')).hexdigest()

        # Parsing of direct subroot elements
        title = item.get('title', None)
        publish_date = parser.parse(item.get('published', None))
        link = item.get('link', None)

        # Parsing from content_encode part
        content = item.get('content', item.get('conetent_encoded'))[0]
        affected_lines = self.__get_element_nonroot_xml(content.value, 'lines').split(',')
        categories = self.__get_element_nonroot_xml(content.value, 'type').replace('&nbsp;', ' ').split(',')
        from_date, to_date = self.__parse_duration(self.__get_element_nonroot_xml(content.value, 'duration'),
                                                   publish_date)

        # Parsing full text description
        full_text_description = item.get('description', None)
        affects_on_lines = self.__parse_affects(full_text_description, affected_lines)

        record = n[id]
        g.add((record, RDF.type, n.TrafficChange))
        g.add((record, n.title, Literal(title, datatype=XSD.string)))
        g.add((record, n.published, Literal(publish_date, datatype=XSD.datetime)))
        g.add((record, n.link, URIRef(link)))
        # g.add((record, n.fullTextDescHTML, Literal(item.get('description', None))))
        # g.add((record, n.fullTextDesc, Literal(BeautifulSoup(item.get
        affects = rdflib.BNode()
        g.add((affects, RDF.type, RDF.Bag))
        g.add((record, n.affect, affects))
        for line in affected_lines:
            affect = rdflib.BNode()
            g.add((affects, RDF.li, affect))
            g.add((affect, n.line, Literal(line, datatype=XSD.string)))
            if line in affects_on_lines:
                g.add((affect, n.reason, Literal(affects_on_lines[line], datatype=XSD.string)))
        categs = rdflib.BNode()
        g.add((categs, RDF.type, RDF.Bag))
        g.add((record, n.catgory, categs))
        for category in categories:
            g.add((categs, RDF.li, Literal(category, datatype=XSD.string)))
        duration = rdflib.BNode()
        g.add((record, n.duration, duration))
        g.add((duration, n.from_date, Literal(from_date, datatype=XSD.datetime)))
        if to_date is not None:
            g.add((duration, n.to_date, Literal(to_date, datatype=XSD.datetime)))

    def __get_element_nonroot_xml(self, xml_text, el_name):
        return xml_text.split('<' + str(el_name) + '>')[1].split('</' + str(el_name) + '>')[0]

    def __parse_duration(self, duration, pub_date):
        duration = duration.split('do odvolání')[0].replace(' ', '').split('-')
        if duration[0].startswith('dnes'):
            from_date = datetime.strptime(duration[0].replace('dnes', ''), "%H:%M")
            from_date = from_date.replace(day=pub_date.day, month=pub_date.month)
        else:
            if len(duration[0]) > 6:
                from_date = datetime.strptime(duration[0], "%d.%m.%H:%M")
            else:
                from_date = datetime.strptime(duration[0], "%d.%m.")
        from_date = from_date.replace(year=pub_date.year, tzinfo=pub_date.tzinfo)
        if from_date < pub_date:  # in case of the end of a year
            from_date = from_date.replace(year=pub_date.year + 1)
        to_date = None
        if len(duration) > 1:
            to_date = datetime.strptime(duration[1], "%d.%m.%H:%M") if len(duration[1]) > 5 else datetime.strptime(
                duration[1], "%H:%M")
            to_date = to_date.replace(year=from_date.year, tzinfo=from_date.tzinfo)
        return from_date, to_date

    def __parse_affects(self, description, affected_lines):
        affects_on_lines = defaultdict()
        soup = BeautifulSoup(description, "lxml")
        for el in soup.findAll('li'):
            if str(el).startswith('<li>Link'):  # can be '<li>Linky' or '<li>Linka':
                for line in [x.text for x in el.findAll('strong') if x.text in affected_lines]:
                    affects_on_lines[line] = ' '.join(
                        [x.text for x in el.findAll('strong') if x.text not in affected_lines])
        return affects_on_lines
