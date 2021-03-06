from py2neo import Graph, Node, Relationship
from hexdump import hexdump
import re
import sys
PATH_MODULE_CONFIG = '../config/'
sys.path.append(PATH_MODULE_CONFIG)
import misc_config


# TODO: There still could be a race condition between static and dynamic analysis when committing!
# TODO Exchange creates with merges!
# TODO Get several found more than 1 in Antivirus results

pw = misc_config.MSNEO_PASSWORD # 'msneo' # After changing password from default password neo4j to msneo

def clean_all():
    graph = Graph(password=pw)
    tx = graph.begin()
    tx.run('MATCH (n) DETACH DELETE n')
    tx.commit()

def show_graph():
    graph = Graph(password=pw)
    graph.run('MATCH (n:Android) return n')
    graph.open_browser()

def add_attribute(node, datadict, attribute, regex=None, upper=False):
    if attribute not in datadict: return
    if regex and not regex.match(datadict[attribute]): return

    if datadict[attribute] == '': return node

    node[attribute] = datadict[attribute]
    if upper: node[attribute] = node[attribute].upper()
    return node

# Splits URI by .
# Returns dictionary with lastURItoken and a short_description with the format: ([<first character of first URI tokens]+)*.<last two URI tokens>
# Short description: Only first character in each URI token, full name in last
def get_short_uri_attributes(datadict):
    list_attributes = []
    for element in datadict:
        dict_description = {'short_description': 'N/A', 'lastURItoken': 'N/A'} # TODO Collusion with descriptions that really are N/A
        list_uri_els = element.split('.')
        if len(element) == 1:
            dict_description['short_description'] = list_uri_els[0]
        else:
            dict_description['short_description'] = '.'.join([ x[0]+'*' for x in list_uri_els[:-1] ])
            dict_description['short_description'] += '.' + '.'.join(list_uri_els[-1:])
        if len(element) > 0:
            dict_description['lastURItoken'] = list_uri_els[-1]
        list_attributes.append(dict_description)
    return list_attributes

# Returns short description for URLs using a pretty weird regex.
# Short description: hostname (IP/domainname without subs) '/' file requested 
def get_short_url_attributes(datadict):
    # TODO Check with multiple test URLs
    # http://stackoverflow.com/questions/27745/getting-parts-of-a-url-regex
    """
        Positions
        ? 0 url
          1 protocol
          2 host
          3 path
          4 file
          5 query
        ? 6 hash
    """
    # Positions:
    urlregex = '^((http[s]?|ftp):\\/)?\\/?([^:\\/\\s]+)((\\/\\w+)*\\/)([\\w\\-\\.]+[^#?\\s]+)(.*)?(#[\\w\\-]+)?$'


    list_attributes = []
    for element in datadict:
        dict_description = {}
        dict_description['short_description'] = 'N/A'
        dict_description['host'] = 'N/A'
        dict_description['file'] = 'N/A'
        results = re.findall(urlregex, element)
        if len(results) == 1:
            results = results[0]
            hostname = results[2]
            requested_file = results[4]
            if len(requested_file) > 0 and requested_file[0] == '/':
                requested_file = requested_file[1:]
            dict_description['host'] = hostname
            dict_description['file'] = requested_file
            dict_description['short_description'] = '{}/{}'.format(hostname, requested_file)
        list_attributes.append(dict_description)

    return list_attributes

# Create a node named nodename in graph using transaction tx that is in relationship with node nrelative, add attributes (same idx list of dicts: attrname -> attr) to nodename if provided.
# TODO Unmangle this function
def create_list_nodes_rels(graph, tx, nrelative, nodename, nodelist, relationshipname, attributes=None, nodematchkey='name', upper=False, relationshipattributes=None):

    modified_related_nodes = []

    # Generate nodes for every new node in nodelist
    for idx, node in enumerate(nodelist):
        if node is None or node=='': continue

        if nodematchkey == 'name':
            valuetomatch = node
        else:
            if not attributes or nodematchkey not in attributes[idx]:
                print 'ERROR: Attributes was empty or nodematchkey {} did not exist in attributes'.format(nodematchkey)
                continue

            valuetomatch = attributes[idx][nodematchkey]

        (count, n) = find_unique_node(graph, nodename, nodematchkey, valuetomatch, upper=upper)

        # Give error if we matched more than 1 nodes
        if count > 1:
            print 'ERROR: Found more than 1 {0} nodes with {0} Name {1}'.format(nodename, node)
            modified_related_nodes.append(None)
            continue

        if count == 0:
            n = Node(nodename)
            if nodematchkey=='name':
                n['name'] = node
            else:
                n['names'] = []
                n['names'].append(node)

            if attributes:
                for attrname, attr in attributes[idx].items():
                    if attrname in n and n[attrname] != attr:
                        print 'ERROR: node {0} - Different Attributes {1} found but {2} expected'.format(nodename, attr, n[attrname])
                        continue

                    n[attrname] = attr

            tx.create(n)
            print 'Neo4J: Created {0} Node with name: {{{1}}}'.format(nodename, node)

        if count == 1 and attributes:
            #changed = False
            if nodematchkey!='name' and node not in n['names']:
                n['names'].append(node)
                #changed = True

            for attrname, attr in attributes[idx].items():
                attr = attr
                if attrname in n and n[attrname] != attr:
                    print 'ERROR: node {0} - Different Attributes {1} found but {2} expected'.format(nodename, attr, n[attrname])
                    continue

                #changed = True
                n[attrname] = attr
            #if changed: print 'Neo4J: Updated Node {}'.format(nodename)

        r = Relationship(nrelative, relationshipname, n)
        if relationshipattributes:
            for attrname, attr in relationshipattributes[idx].items():
                r[attrname] = attr
        tx.merge(r)
        modified_related_nodes.append(n)
    return modified_related_nodes

def find_unique_node(graph, nodename, key, value, upper=False, maxn=3):
    if upper: value = value.upper()
    gen = graph.find(nodename, property_key=key, property_value=value)
    (first, count, node) = (True, 0, None)
    for i in range(1,maxn):
        try:
            if first:
                node = gen.next()
                first = False
            else:
                _ = gen.next()
            count += 1
        except StopIteration:
            break
    if count==0: return (0, None)
    elif count == 1: return (1, node)
    else: return (count, node)


# A node consists of only identifying information / attributes about itself. Any other extra information that can be used by other nodes is moved to a new node class
# Transfer an Android Application node with feature vectors / attributes generated by the static or dynamic analyzer
# TODO Merge duplicates instead of creating a new node
# TODO Test for != ''
# TODO Error cases count > 1 print to stderr and do something
def create_node_static(datadict):
    print 'Transferring static data to Neo4J database'
    # TODO: Move compiled regex to somewhere only executed once
    r_md5    = re.compile(r'[a-fA-F\d]{32}')
    r_sha1   = re.compile(r'[a-fA-F\d]{40}')
    r_sha256 = re.compile(r'[a-fA-F\d]{64}')

    graph = Graph(password=pw)
    tx = graph.begin()


    (count, na) = find_unique_node(graph, 'Android', 'sha256', datadict['sha256'], upper=True)

    # Give error if we matched more than 1 nodes
    if count > 1:
        print 'ERROR: Found more than 1 Android nodes with SHA256 {}'.format(datadict['sha256'].upper())
        tx.commit()
        return

    # If we found the Android Application already in the Neo4J database, then we already did the following. Abort here
    if count == 1 and na['dynamic']:
        print 'Neo4J: Found Android Node with sha256: {}'.format(datadict['sha256'])
        tx.commit()
        return


    if count == 0:
        # Create Android Node
        na = Node('Android')
        add_attribute(na, datadict, 'md5', regex=r_md5, upper=True)
        add_attribute(na, datadict, 'sha1', regex=r_sha1, upper=True)
        add_attribute(na, datadict, 'sha256', regex=r_sha256, upper=True)
        add_attribute(na, datadict, 'ssdeep')
        if 'app_name' in datadict:
            add_attribute(na, datadict, 'app_name')
        else:
            na['app_name'] = 'N/A'
        na['static'] = True
        tx.create(na)

    print 'Neo4J: Static Got Android Node with sha256: {}'.format(datadict['sha256'])

    # Create nodes with only a name attribute
    permissions = set(datadict['app_permissions'])
    permissions |= set(datadict['api_permissions']) # TODO Difference app/api permissions
    # Create Permission nodes
    list_attributes = get_short_uri_attributes(permissions)
    nodes_permissions = create_list_nodes_rels(graph, tx, na, 'Permission', permissions, 'USES_PERMISSION', attributes = list_attributes)

    # Create Intent nodes
    # Short description: *.<last two URI tokens>
    list_attributes = []
    for intent in datadict['intents']:
        dict_description = {'short_description': 'N/A', 'lastURItoken': 'N/A'} # TODO Collusion with descriptions that really are N/A
        list_uri_els = intent.split('.')
        if len(intent) == 1:
            dict_description['short_description'] = list_uri_els[0]
        elif len(intent) == 2:
            dict_description['short_description'] = '.'.join(list_uri_els)
        else:
            dict_description['short_description'] = '*.'+'.'.join(list_uri_els[-2:])
        if len(intent) > 0:
            dict_description['lastURItoken'] = list_uri_els[-1]
        list_attributes.append(dict_description)
    create_list_nodes_rels(graph, tx, na, 'Intent', datadict['intents'], 'ACTION_WITH_INTENT', attributes=list_attributes)

    # Create Activity nodes
    list_attributes = get_short_uri_attributes(datadict['activities'])
    create_list_nodes_rels(graph, tx, na, 'Activity', datadict['activities'], 'ACTIVITY', attributes=list_attributes)

    # Create Feature nodes
    list_attributes = get_short_uri_attributes(datadict['features'])
    create_list_nodes_rels(graph, tx, na, 'Feature', datadict['features'], 'FEATURE', attributes=list_attributes)

    # Create Provider nodes
    list_attributes = get_short_uri_attributes(datadict['providers'])
    create_list_nodes_rels(graph, tx, na, 'Provider', datadict['providers'], 'PROVIDER', attributes=list_attributes)

    # Create Service and Receiver nodes
    # TODO Split s_and_r
    list_attributes = get_short_uri_attributes(datadict['s_and_r'])
    create_list_nodes_rels(graph, tx, na, 'Service_Receiver', datadict['s_and_r'], 'SERVICE_RECEIVER', attributes=list_attributes)

    # Create package name nodes
    list_attributes = get_short_uri_attributes([datadict['package_name']])
    create_list_nodes_rels(graph, tx, na, 'Package_Name', [ datadict['package_name']], 'PACKAGE_NAME', attributes=list_attributes)

    # Create SDK Version nodes
    create_list_nodes_rels(graph, tx, na, 'SDK_Version_Target', [ datadict['sdk_version_target']], 'SDK_VERSION_TARGET')
    create_list_nodes_rels(graph, tx, na, 'SDK_Version_Min', [ datadict['sdk_version_min']], 'SDK_VERSION_MIN')
    create_list_nodes_rels(graph, tx, na, 'SDK_Version_Max', [ datadict['sdk_version_max']], 'SDK_VERSION_MAX')

    # Create appname nodes
    create_list_nodes_rels(graph, tx, na, 'App_Name', [ datadict['app_name']], 'APP_NAME')

    # Create URL nodes
    list_attributes = get_short_url_attributes(datadict['urls'])
    create_list_nodes_rels(graph, tx, na, 'URL', datadict['urls'], 'CONTAINS_URL', attributes=list_attributes)


    #create_list_nodes_rels(graph, tx, na, 'Networks', datadict['networks'], 'NETWORK')
    create_list_nodes_rels(graph, tx, na, 'AD_Network', datadict['detected_ad_networks'], 'AD_NETWORK')


    # Create nodes that may result in a high number of nodes, only have a name attribute
    create_list_nodes_rels(graph, tx, na, 'DEX_File', datadict['included_files_src'], 'INCLUDES_FILE_SRC')
    if misc_config.ENABLE_PARSING_STRINGS: create_list_nodes_rels(graph, tx, na, 'String', datadict['strings'], 'CONTAINS_STRING')
    if misc_config.ENABLE_PARSING_FIELDS: create_list_nodes_rels(graph, tx, na, 'Field', datadict['fields'], 'CONTAINS_FIELD')
    if misc_config.ENABLE_PARSING_CLASSES: create_list_nodes_rels(graph, tx, na, 'Class', datadict['classes'], 'CONTAINS_CLASS')
    if misc_config.ENABLE_PARSING_METHODS: create_list_nodes_rels(graph, tx, na, 'Method', datadict['methods'], 'CONTAINS_METHOD')


    # Nodes with special attributes
    nodes_api_calls = create_list_nodes_rels(graph, tx, na, 'API_Call', datadict['api_calls'].keys(), 'CALLS', attributes=datadict['api_calls'].values())
    # TODO: Add relationship APICall -[CALL_USES_PERMISSION]->Permission
    TODO="""
    if nodes_api_calls:
        for node_permission in graph.find('Permission'):
            if node_permission in nodes_permissions: continue
            nodes_permissions.append(node_permission)

        dict_api_call_name_to_node = {}
        dict_permissions_name_to_node = {}
        for node in nodes_api_calls:
            if not node: continue
            dict_api_call_name_to_node[node['name']] = node
        for node in nodes_permissions:
            if not node: continue
            dict_permissions_name_to_node[node['name']] = node
        # TODO Either separate dicts and only parse api_calls once or do it twice: here and in django template views
        for api_call_name, api_call_attributes in datadict['api_calls'].items():
            if 'permission' not in api_call_attributes: continue
            if api_call_name not in dict_api_call_name_to_node: continue
            print 'Find {} in {}'.format(api_call_attributes['permission'], dict_permissions_name_to_node)
            if api_call_attributes['permission'] not in dict_permissions_name_to_node: continue
            print 3
            r = Relationship(dict_api_call_name_to_node[api_call_name], 'CALL_REQUESTS_PERMISSION', dict_permissions_name_to_node[api_call_attributes['permission']])
            tx.create(r)
            print '----------------------'
    """

    # TODO SocketTimeout - takes too long?
    if misc_config.ENABLE_ZIPFILE_HASHING:
        # Add Nodes and Relationships with more than 1 attribute
        included_files = []
        included_files_attrdicts = []
        for fileinzip, attrdict in datadict['included_files'].items():
            included_files.append(fileinzip)
            included_files_attrdicts.append(attrdict)

        # TODO  Somehow higher O than Dex and pretty slow
        tmp_nodes = create_list_nodes_rels(graph, tx, na, 'File', included_files, 'INCLUDES_FILE', attributes=included_files_attrdicts, nodematchkey='md5', upper=True)
        #graph.push(tmp_nodes) # TODO Doesn't work!

    # Abort if Certificate Dict is empty
    if not datadict['cert']:
        tx.commit()
        return

    certdict = datadict['cert']

    (count, nc) = find_unique_node(graph, 'Certificate', 'Sha1Thumbprint', certdict['Sha1Thumbprint'], upper=True)

    # Give error if we matched more than 1 nodes
    if count > 1:
        print 'ERROR: Found more than 1 Certificate nodes with Sha1Thumbprint {}'.format(certdict['Sha1Thumbprint'].upper())
        tx.commit()
        return

    # NOTE: It is currently presumed that static analysis occurs before dynamic analysis
    if count == 1:
        print 'Neo4J: Found Certificate Node with Sha1Thumbprint: {}'.format(certdict['Sha1Thumbprint'])

        # Create SIGNED_WITH Relationship between Android Application and Certificate. Then Abort
        r = Relationship(na, 'SIGNED_WITH', nc)
        tx.create(r)
        tx.commit()
        return

    # Create Certificate Node with its distinguishable and boolean attributes
    nc = Node('Certificate')
    add_attribute(nc, certdict, 'CertVersion')
    add_attribute(nc, certdict, 'Expired')
    add_attribute(nc, certdict, 'ForClientAuthentication')
    add_attribute(nc, certdict, 'ForCodeSigning')
    add_attribute(nc, certdict, 'ForSecureEmail')
    add_attribute(nc, certdict, 'ForServerAuthentication')
    add_attribute(nc, certdict, 'ForTimeStamping')
    add_attribute(nc, certdict, 'IsRoot')
    add_attribute(nc, certdict, 'IssuerDN')
    add_attribute(nc, certdict, 'Revoked')
    add_attribute(nc, certdict, 'SelfSigned')
    add_attribute(nc, certdict, 'SignatureVerified')
    add_attribute(nc, certdict, 'SubjectDN')
    add_attribute(nc, certdict, 'SerialNumber')
    add_attribute(nc, certdict, 'SubjectKeyId')
    add_attribute(nc, certdict, 'Sha1Thumbprint', regex=r_sha1, upper=True)
    add_attribute(nc, certdict, 'TrustedRoot')
    add_attribute(nc, certdict, 'validFromStr')
    add_attribute(nc, certdict, 'validToStr')
    tx.create(nc)
    print 'Neo4J: Created Certificate Node with Sha1Thumbprint: {}'.format(certdict['Sha1Thumbprint'])

    # Create SIGNED_WITH Relationship between Android Application and Certificate
    r = Relationship(na, 'SIGNED_WITH', nc)
    tx.create(r)

    # Create certificate related nodes describing common attributes
    if 'IssuerC' in certdict: create_list_nodes_rels(graph, tx, nc, 'IssuerC', [certdict['IssuerC'],], 'ISSUER_COUNTRY')
    if 'IssuerCN' in certdict: create_list_nodes_rels(graph, tx, nc, 'IssuerCN', [certdict['IssuerCN'],], 'ISSUER_COMMON_NAME')
    if 'IssuerE' in certdict: create_list_nodes_rels(graph, tx, nc, 'IssuerE', [certdict['IssuerE'],], 'ISSUER_EMAIL')
    if 'IssuerL' in certdict: create_list_nodes_rels(graph, tx, nc, 'IssuerL', [certdict['IssuerL'],], 'ISSUER_LOCALITY')
    if 'IssuerO' in certdict: create_list_nodes_rels(graph, tx, nc, 'IssuerO', [certdict['IssuerO'],], 'ISSUER_ORGANIZATION')
    if 'IssuerOU' in certdict: create_list_nodes_rels(graph, tx, nc, 'IssuerOU', [certdict['IssuerOU'],], 'ISSUER_ORGAN_UNIT')
    if 'IssuerS' in certdict: create_list_nodes_rels(graph, tx, nc, 'IssuerS', [certdict['IssuerS'],], 'ISSUER_STATE')

    if 'SubjectC' in certdict: create_list_nodes_rels(graph, tx, nc, 'SubjectC', [certdict['SubjectC'],], 'SUBJECT_COUNTRY')
    if 'SubjectCN' in certdict: create_list_nodes_rels(graph, tx, nc, 'SubjectCN', [certdict['SubjectCN'],], 'SUBJECT_COMMON_NAME')
    if 'SubjectE' in certdict: create_list_nodes_rels(graph, tx, nc, 'SubjectE', [certdict['SubjectE'],], 'SUBJECT_EMAIL')
    if 'SubjectL' in certdict: create_list_nodes_rels(graph, tx, nc, 'SubjectL', [certdict['SubjectL'],], 'SUBJECT_LOCALITY')
    if 'SubjectO' in certdict: create_list_nodes_rels(graph, tx, nc, 'SubjectO', [certdict['SubjectO'],], 'SUBJECT_ORGANIZATION')
    if 'SubjectOU' in certdict: create_list_nodes_rels(graph, tx, nc, 'SubjectOU', [certdict['SubjectOU'],], 'SUBJECT_ORGAN_UNIT')
    if 'SubjectS' in certdict: create_list_nodes_rels(graph, tx, nc, 'SubjectS', [certdict['SubjectS'],], 'SUBJECT_STATE')

    if 'AuthorityKeyId' in certdict: create_list_nodes_rels(graph, tx, nc, 'AuthorityKeyId', [certdict['AuthorityKeyId'],], 'CERT_AUTHORITY_KEYID')
    if 'OcspUrl' in certdict: create_list_nodes_rels(graph, tx, nc, 'OcspUrl', [certdict['OcspUrl'],], 'CERT_OCSP_URL')
    if 'Rfc822Name' in certdict: create_list_nodes_rels(graph, tx, nc, 'Rfc822Name', [certdict['Rfc822Name'],], 'CERT_RFC822_NAME')
    if 'Version' in certdict: create_list_nodes_rels(graph, tx, nc, 'Version', [certdict['Version'],], 'CERT_CONTENT_VERSION')


    # Abort if Public Key Dict is empty
    if certdict['pubkey']['keytype'] is None:
        tx.commit()
        return

    pubdict = certdict['pubkey']

    # TODO MATCH PublicKeys

    # Create Public Key Node
    np = Node('PublicKey')
    if pubdict['keytype'] == 'RSA':
        add_attribute(np, pubdict, 'keytype')
        add_attribute(np, pubdict, 'modulus')
        add_attribute(np, pubdict, 'exponent')
    elif pubdict['keytype'] == 'DSA':
        add_attribute(np, pubdict, 'keytype')
        add_attribute(np, pubdict, 'P')
        add_attribute(np, pubdict, 'Q')
        add_attribute(np, pubdict, 'G')
        add_attribute(np, pubdict, 'Y')
    elif pubdict['keytype'] == 'ECC':
        add_attribute(np, pubdict, 'keytype')
        pass

    tx.create(np)
    print 'Neo4J: Created PublicKey Node with keytype: {}'.format(pubdict['keytype'])

    # Create AUTHENTICATED_BY Relationship between Certificate and Public Key
    r = Relationship(nc, 'AUTHENTICATED_BY', np)
    tx.create(r)


    tx.commit()

def create_node_dynamic(datadict):
    print 'Transferring dynamic data to Neo4J database'

    r_md5    = re.compile(r'[a-fA-F\d]{32}')
    r_sha1   = re.compile(r'[a-fA-F\d]{40}')
    r_sha256 = re.compile(r'[a-fA-F\d]{64}')

    if 'target' not in datadict:
        print 'ERROR: Key "target" is not in dictionary. See following output'
        hexdump(datadict)
        return

    graph = Graph(password=pw)
    tx = graph.begin()

    (count, na) = find_unique_node(graph, 'Android', 'sha256', datadict['target']['file']['sha256'], upper=True)

    # Give error if we matched more than 1 nodes
    if count > 1:
        print 'ERROR: Found more than 1 Android nodes with SHA256 {}'.format(datadict['target']['file']['sha256'].upper())
        tx.commit()
        return

    if count == 0:
        # Create Android Node
        na = Node('Android')
        add_attribute(na, datadict['target']['file'], 'md5', regex=r_md5, upper=True)
        add_attribute(na, datadict['target']['file'], 'sha1', regex=r_sha1, upper=True)
        add_attribute(na, datadict['target']['file'], 'sha256', regex=r_sha256, upper=True)
        na['dynamic'] = True
        tx.create(na)
    else:
        na['dynamic'] = True

    print 'Neo4J: Android Node with sha256: {}'.format(na['sha256'])

    # Create virustotal nodes
    if 'virustotal' in datadict and 'permalink' in datadict['virustotal']:
        set_av_results = set()
        for antivirus, resultdict in datadict['virustotal']['scans'].items():
            if not resultdict['result']: continue # Skip null results
            set_av_results.add(resultdict['result'])
        create_list_nodes_rels(graph, tx, na, 'Antivirus', list(set_av_results), 'ANTIVIRUS')

    # Create nodes from apkinfo
    if 'apkinfo' in datadict:
        # Create files nodes including generated md5 sums
        # [{
        #   'size'           : integer  # Size of the file
        #   'type'           : string   # Type of the file - unknown if pip install python-magic hasn't been done beforehand
        #   'name'           : string   # Name of the file
        #   'md5'            : string   # MD5 Hash 
        # }]
        # TODO: This is redundant information if we enable zipfile hashing
        if 'files' in datadict['apkinfo']:
            # Map from md5(file) -> index
            dict_map_files = {}
            list_files = []
            list_files_attributes = []
            max_index = 0
            for dict_file in datadict['apkinfo']['files']:
                dict_file['md5']=dict_file['md5'].upper()
                fileidname = '{}_{}'.format(dict_file['md5'],dict_file['name']) # TODO Add names in a proper way
                if dict_file['md5'] in dict_map_files:
                    list_index = dict_map_files[dict_file['md5']]
                    list_files_attributes[list_index][fileidname] = dict_file['name']
                else:
                    list_files_attributes.append(dict_file)
                    list_files_attributes[max_index][fileidname] = dict_file['name']
                    dict_map_files[dict_file['md5']] = max_index
                    del list_files_attributes[max_index]['name']
                    list_files.append(dict_file['md5'])
                    max_index += 1
            node_files = create_list_nodes_rels(graph, tx, na, 'File', list_files, 'CONTAINS_FILE', attributes=list_files_attributes, nodematchkey='md5', upper=True)



    # Add network traffic data
    # Add contacted IPs through UDP with additional relationship attributes. Result built from dpkt
    localhost = '192.168.56.10' # TODO Move this
    if 'network' in datadict:
        # TODO Merge domains + hosts
        # Case 'hosts': https://github.com/brad-accuvant/cuckoo-modified/blob/master/modules/processing/network.py#L666
        # list [
        #   string # List of non-private IP addresses
        # ]
        # Generate initial hosts list
        nodes_hosts = []
        if 'hosts' in datadict['network'] and len(datadict['network']['hosts']) > 0:
            nodes_hosts = create_list_nodes_rels(graph, tx, na, 'Host', datadict['network']['hosts'], 'NETWORK_CONTACT')

        # Hosts dict for a quick lookup
        dict_hosts = {}
        for node in nodes_hosts:
            dict_hosts[node['name']] = node

        # Case 'udp': https://github.com/brad-accuvant/cuckoo-modified/blob/master/modules/processing/network.py#L622
        # [{ 
        #   'src'           : string        # Source IP
        #   'src'           : string        # Destination IP
        #   'offset'        : integer       # Offset to dumpfile
        #   'time'          : integer       # Time vector in dumpfile
        #   'sport'         : integer       # Source Port
        #   'dport'         : integer       # Destination Port
        # }]
        if 'udp' in datadict['network'] and len(datadict['network']['udp']) > 0:
            dict_udp_hosts = {}
            for udpdict in datadict['network']['udp']:
                remotehost = None
                remoteport = None
                if udpdict['src'] == localhost:
                    remotehost = udpdict['dst']
                    remoteport = udpdict['dport']
                elif udpdict['dst'] == localhost:
                    remotehost = udpdict['src']
                    remoteport = udpdict['sport']
                else:
                    print 'ERROR: Neither src nor dst is localhost {} in UDP connection. Real values: dst {}, src: {}'.format(localhost, udpdict['dst'], udpdict['src'])
                    continue
                if remotehost not in dict_udp_hosts:
                    dict_udp_hosts[remotehost] = set()
                dict_udp_hosts[remotehost].add(remoteport)

            for hostname, ports in dict_udp_hosts.items():
                create_list_nodes_rels(graph, tx, dict_hosts[hostname], 'Port', ports, 'OPENED_PORT')

        # Case 'dns': https://github.com/brad-accuvant/cuckoo-modified/blob/master/modules/processing/network.py#L283
        # [{
        #   'type'          : string        # Query Type: A, AAAA etc
        #   'request'       : string        # Query Name: Domain Name
        #   'answers'       : list          # Answers
        #   [
        #          'data':     : string     # Query Data, e.g. IP on A, domain name on CNAME etc - depending on Query Type
        #          'type':     : string     # Query Type
        #   ]
        # }]
        if 'dns' in datadict['network'] and len(datadict['network']['dns']) > 0:
            dns_requests = [ dnsdict['request'] for dnsdict in datadict['network']['dns'] ]
            nodes_requests = create_list_nodes_rels(graph, tx, na, 'DNS_Request', dns_requests, 'RESOLVE_DOMAIN_NAME')

        # Case 'domains': https://github.com/brad-accuvant/cuckoo-modified/blob/master/modules/processing/network.py#L397
        # [{
        #   'domain'    : string  # Domain Name
        #   'ip'        : string  # IP
        # }]
        dict_map_domains = {}
        if 'domains' in datadict['network'] and len(datadict['network']['domains']) > 0:
            for dict_domain in datadict['network']['domains']:
                node_domain = create_list_nodes_rels(graph, tx, na, 'Domain', [dict_domain['domain']], 'NETWORK_CONTACT')
                dict_map_domains[dict_domain['domain']] = node_domain
                if dict_domain['ip'] != '':
                    create_list_nodes_rels(graph, tx, node_domain, 'IP', [dict_domain['ip']], 'RESOLVED_IP')

        # Case HTTP:
        # [{
        #   'count'         : integer   # Number of same requests
        #   'body'          : string    # HTTP Body parsed from a file object (cuckoo uses dpkt http://dpkt.readthedocs.io/en/latest/_modules/dpkt/http.html?highlight=body )
        #   'uri'           : string    # URI/Full URL
        #   'user-agent'    : string    # Useragent
        #   'method'        : string    # GET/POST etc
        #   'host'          : string    # Host/Domainname without protocol and directory
        #   'version'       : string    # HTTP Version
        #   'path'          : string    # Path including file, but without domain prefix
        #   'data'          : string    # Request verbatim (do not confuse this with the response - which doesn't exist somehow)
        #   'port'          : integer   # Port number contacted
        # }]
        if 'http' in datadict['network'] and len(datadict['network']['http']) > 0:
            # NOTE Since domain is the same as host right now (not the IP), we will use the domain nodes
            # Create relationships from host to contacting sample with attributes (useful to e.g. display the URI instead of rel. type)
            for dict_http in datadict['network']['http']:
                # If the domain hasn't been created before, create it now
                # NOTE This should not happen, since we created domain nodes beforehand and all contacted domains/host names are listed in the previous dict
                # TODO Merge hosts and domains to avoid a conflict
                node_domain = None
                if dict_http['host'] not in dict_map_domains:
                    node_domain = create_list_nodes_rels(graph, tx, na, 'Domain', [dict_http['host']], 'NETWORK_CONTACT')
                    dict_map_domains[dict_http['host']] = node_domain
                if not node_domain: node_domain = dict_map_domains[dict_http['host']]
                r = Relationship(na, 'HTTP_REQUEST', node_domain) # TODO ,dict_http => Hyperedges not supported
                for attrname, attr in dict_http.items():
                    r[attrname] = attr
                tx.merge(r)
                print 'Neo4J: Created {0} Relationship with name: {{{1}}}'.format('HTTP_REQUEST', node_domain)


        # Case TCP: TODO
        if 'tcp' in datadict['network'] and len(datadict['network']['tcp']) > 0:
            pass
        # Case IRC: TODO
        if 'irc' in datadict['network'] and len(datadict['network']['irc']) > 0:
            pass

        # Case SMTP: TODO
        if 'smtp' in datadict['network'] and len(datadict['network']['smtp']) > 0:
            pass

        # Case ICMP: TODO
        if 'icmp' in datadict['network'] and len(datadict['network']['icmp']) > 0:
            pass
    tx.commit()
