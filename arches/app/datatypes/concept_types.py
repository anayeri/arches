import uuid
import csv
from arches.app.models import models
from arches.app.models import concept
from arches.app.models.system_settings import settings
from arches.app.datatypes.base import BaseDataType
from arches.app.datatypes.datatypes import DataTypeFactory
from arches.app.models.concept import get_preflabel_from_valueid, get_preflabel_from_conceptid, get_valueids_from_concept_label
from arches.app.search.elasticsearch_dsl_builder import Bool, Match, Range, Term, Nested, Exists
from arches.app.utils.date_utils import ExtendedDateFormat
from django.core.exceptions import ObjectDoesNotExist

# for the RDF graph export helper functions
from rdflib import Namespace, URIRef, Literal, Graph, BNode
from rdflib.namespace import RDF, RDFS, XSD, DC, DCTERMS, SKOS
from arches.app.models.concept import ConceptValue
archesproject = Namespace(settings.ARCHES_NAMESPACE_FOR_DATA_EXPORT)
cidoc_nm = Namespace("http://www.cidoc-crm.org/cidoc-crm/")


class BaseConceptDataType(BaseDataType):
    def __init__(self, model=None):
        super(BaseConceptDataType, self).__init__(model=model)
        self.value_lookup = {}

    def get_value(self, valueid):
        try:
            return self.value_lookup[valueid]
        except:
            self.value_lookup[valueid] = models.Value.objects.get(pk=valueid)
            return self.value_lookup[valueid]

    def get_concept_export_value(self, valueid, concept_export_value_type=None):
        ret = ''
        if concept_export_value_type == None or concept_export_value_type == '' or concept_export_value_type == 'label':
            ret = self.get_value(valueid).value
        elif concept_export_value_type == 'both':
            ret = valueid + '|' + self.get_value(valueid).value
        elif concept_export_value_type == 'id':
            ret = valueid
        return ret

    def get_concept_dates(self, concept):
        result = None
        date_range = {}
        values = models.Value.objects.filter(concept=concept)
        for value in values:
            if value.valuetype.valuetype in ('min_year' 'max_year'):
                date_range[value.valuetype.valuetype] = value.value
        if 'min_year' in date_range and 'max_year' in date_range:
            result = date_range
        return result

    def append_to_document(self, document, nodevalue, nodeid, tile, provisional=False):
        try:
            assert isinstance(nodevalue, (list, tuple)) #assert nodevalue is an array
        except AssertionError:
            nodevalue = [nodevalue]
        for valueid in nodevalue:
            value = self.get_value(valueid)
            date_range = self.get_concept_dates(value.concept)
            if date_range is not None:
                min_date = ExtendedDateFormat(date_range['min_year']).lower
                max_date = ExtendedDateFormat(date_range['max_year']).upper
                if {'gte': min_date, 'lte': max_date} not in document['date_ranges']:
                    document['date_ranges'].append({'date_range': {'gte': min_date, 'lte': max_date}, 'nodegroup_id': tile.nodegroup_id, 'provisional': provisional})
            document['domains'].append({'label': value.value, 'conceptid': value.concept_id, 'valueid': valueid, 'nodegroup_id': tile.nodegroup_id, 'provisional': provisional})
            document['strings'].append({'string': value.value, 'nodegroup_id': tile.nodegroup_id, 'provisional': provisional})


class ConceptDataType(BaseConceptDataType):

    def validate(self, value, row_number=None, source=''):
        errors = []

        ## first check to see if the validator has been passed a valid UUID,
        ## which should be the case at this point. return error if not.
        if value != None:
            try:
                uuid.UUID(str(value))
            except ValueError:
                message = "This is an invalid concept prefLabel, or an incomplete UUID"
                errors.append({'type': 'ERROR', 'message': 'datatype: {0} value: {1} {2} {3} - {4}. {5}'.format(self.datatype_model.datatype, value, source, row_number, message, 'This data was not imported.')})
                return errors

            ## if good UUID, test whether it corresponds to an actual Value object
            try:
                models.Value.objects.get(pk=value)
            except ObjectDoesNotExist:
                message = "This UUID does not correspond to a valid domain value"
                errors.append({'type': 'ERROR', 'message': 'datatype: {0} value: {1} {2} {3} - {4}. {5}'.format(self.datatype_model.datatype, value, source, row_number, message, 'This data was not imported.')})
        return errors

    def transform_import_values(self, value, nodeid):
        return value.strip()

    def transform_export_values(self, value, *args, **kwargs):
        if 'concept_export_value_type' in kwargs:
            concept_export_value_type = kwargs.get('concept_export_value_type')
        return self.get_concept_export_value(value, concept_export_value_type)

    def get_pref_label(self, nodevalue, lang='en-US'):
        return get_preflabel_from_valueid(nodevalue, lang)['value']

    def get_display_value(self, tile, node):
        if tile.data[str(node.nodeid)] is None or tile.data[str(node.nodeid)].strip() == '':
            return ''
        else:
            return self.get_value(uuid.UUID(tile.data[str(node.nodeid)])).value

    def append_search_filters(self, value, node, query, request):
        try:
            if value['val'] != '':
                match_query = Match(field='tiles.data.%s' % (str(node.pk)), type="phrase", query=value['val'], fuzziness=0)
                if '!' in value['op']:
                    query.must_not(match_query)
                    query.filter(Exists(field="tiles.data.%s" % (str(node.pk))))
                else:
                    query.must(match_query)

        except KeyError, e:
            pass

    def to_rdf(self, edge_info, edge):
        g = Graph()
        # logic: No data -> empty graph
        #        concept_id, but no value -> node linked to class of Concept, no label
        #        value but no concept_id -> node linked to BNode, labelled
        #        concept_id + value -> normal expected functionality

        def get_rangenode(arches_uri, ext_ids):
            rangenode = arches_uri

            for id_uri in ext_ids:
                if str(id_uri).startswith(settings.PREFERRED_CONCEPT_SCHEME):
                    rangenode = id_uri
            return rangenode

        if edge_info['range_tile_data'] is not None:
            c = ConceptValue(str(edge_info['range_tile_data']))

            # create a default node
            arches_uri = BNode()
            ext_idents = []
            # Use the conceptid URI rather than the pk for the ConceptValue
            if c.conceptid is not None:
                arches_uri = URIRef(archesproject['concepts/%s' % c.conceptid])

                # get other identifiers:
                ext_idents = [ident.value for ident in models.Value.objects.all().filter(concept_id=c.conceptid,
                                                                                  valuetype__category="identifiers")]
            rangenode = get_rangenode(arches_uri, ext_idents)

            g.add((rangenode, RDF.type, URIRef(edge.rangenode.ontologyclass)))
            g.add((edge_info['d_uri'], URIRef(edge.ontologyproperty), rangenode))

            assert c.value is not None, "Null or blank concept value"
            g.add((rangenode, URIRef(RDFS.label), Literal(c.value, lang=c.language)))

        return g

    def from_rdf(self, json_ld_node):
        # Expects a label and a concept URI within the json_ld_node

        # FIXME: SHOULD be able to handle cases when the label is not supplied,
        # or if the label does not match any label from the ConceptValue
        # Either by instantiating a keyword without a concept_id or by
        # or by looking for say an external identifier attached to the concept and
        # building upon that.
        concept_uri = json_ld_node.get('id')
        label = json_ld_node.get(str(RDFS.label))

        concept_id = None
        import re
        p = re.compile(r"(http|https)://(?P<host>[^/]*)/concepts/(?P<concept_id>[A-Fa-f0-9\-]*)/?$")
        m = p.match(concept_uri)
        if m is not None:
            concept_id = m.groupdict().get("concept_id")

        # FIXME: assert that the type of this node is a E55_Type?

        # FIXME when pyld supports uppercase lang in strings, include
        # language handling here.

        if label:
            # Could be:
            #  - Blank node E55_Type with a label - a Keyword
            #  - Concept ID URI, with a label - a conventional Concept
            # find a matching Concept Value to the label
            values = get_valueids_from_concept_label(label, concept_id)

            if values:
                return values[0]["id"]
            else:
                if concept_id:
                    print("FAILED TO FIND MATCHING LABEL '{0}' FOR CONCEPT '{1}'").format(
                        label, concept_id)
                    label = None
                else:
                    print("No Concept ID URI supplied for rdf")

        if concept_id and label is None:
            # got a concept URI but the label is nonexistant
            # or cannot be resolved in Arches
            value = get_preflabel_from_conceptid(concept_id, lang=None)
            return value['id']

        if concept_id is None and (label is None or label == ""):
            # a keyword of some type. If the code execution gets here their either
            # was no RDFS:label literal value to note or the keyword cannot be found
            # amongst the current Arches ConceptValues
            pass


class ConceptListDataType(BaseConceptDataType):
    def validate(self, value, row_number=None, source=''):
        errors = []

        ## iterate list of values and use the concept validation on each one
        if value != None:
            validate_concept = DataTypeFactory().get_instance('concept')
            for v in value:
                val = v.strip()
                errors += validate_concept.validate(val, row_number)
        return errors

    def transform_import_values(self, value, nodeid):
        ret =[]
        for val in csv.reader([value], delimiter=',', quotechar='"'):
            for v in val:
                ret.append(v.strip())
        return ret

    def transform_export_values(self, value, *args, **kwargs):
        new_values = []
        for val in value:
            new_val = self.get_concept_export_value(val, kwargs['concept_export_value_type'])
            new_values.append(new_val)
        return ','.join(new_values)

    def get_display_value(self, tile, node):
        new_values = []
        if tile.data[str(node.nodeid)]:
            for val in tile.data[str(node.nodeid)]:
                new_val = self.get_value(uuid.UUID(val))
                new_values.append(new_val.value)
        return ','.join(new_values)

    def append_search_filters(self, value, node, query, request):
        try:
            if value['val'] != '':
                match_query = Match(field='tiles.data.%s' % (str(node.pk)), type="phrase", query=value['val'], fuzziness=0)
                if '!' in value['op']:
                    query.must_not(match_query)
                    query.filter(Exists(field="tiles.data.%s" % (str(node.pk))))
                else:
                    query.must(match_query)

        except KeyError, e:
            pass

    def to_rdf(self, edge_info, edge):
        g = Graph()
        c = ConceptDataType()
        for r in edge_info['range_tile_data']:
            concept_info = edge_info.copy()
            concept_info['range_tile_data'] = r
            g += c.to_rdf(concept_info, edge)
        return g
