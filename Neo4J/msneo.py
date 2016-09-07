from py2neo import Graph, Node, Relationship
from hexdump import hexdump
import misc_config
import re

# TODO: There still could be a race condition between static and dynamic analysis when committing!
# TODO Exchange creates with merges!
# TODO Get several found more than 1 in Antivirus results

pw = 'msneo' # After changing password from default password neo4j to msneo

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

    if datadict[attribute] != '':
        node[attribute] = datadict[attribute]
        if upper: node[attribute] = node[attribute].upper()
    return node


# Create a node named nodename in graph using transaction tx that is in relationship with node nrelative, add attributes (same idx list of dicts: attrname -> attr) to nodename if provided.
# TODO Unmangle this function
def create_list_nodes_rels(graph, tx, nrelative, nodename, nodelist, relationshipname, attributes=None, nodematchkey='name', upper=False):

    # Generate nodes for every new node in nodelist
    # TODO Ignore case?
    for idx, node in enumerate(nodelist):
        if node is None: continue

        if nodematchkey == 'name':
            valuetomatch = node
        else:
            if not attributes or nodematchkey not in attributes[idx]:
                print 'ERROR: Attributes was empty or nodematchkey {} did not exist in attributes'.format(nodematchkey)
                return

            valuetomatch = attributes[idx][nodematchkey]

        (count, n) = find_unique_node(graph, nodename, nodematchkey, valuetomatch, upper=upper)

        # Give error if we matched more than 1 nodes
        if count > 1:
            print 'ERROR: Found more than 1 {0} nodes with {0} Name {1}'.format(nodename, node)
            continue

        if count == 0:
            n = Node(nodename)
            n['names'] = []
            n['names'].append(node)
            if attributes:
                for attrname, attr in attributes[idx].items():
                    if attrname in n and n[attrname] != attr:
                        print 'ERROR: node {0} - Different Attributes {1} found but {2} expected'.format(nodename, attr, n[attrname])
                        continue

                    n[attrname] = attr
            tx.create(n)
            print 'Neo4J: Created {0} Node with name: {1}'.format(nodename, node)

        if count == 1 and attributes:
            if node not in n['names']:
                n['names'].append(node)

            for attrname, attr in attributes[idx].items():
                if attrname in n and n[attrname] != attr:
                    print 'ERROR: node {0} - Different Attributes {1} found but {2} expected'.format(nodename, attr, n[attrname])
                    continue

                n[attrname] = attr
            n.push()

        r = Relationship(nrelative, relationshipname, n)
        tx.merge(r)

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
        na['static'] = True
        tx.create(na)

    print 'Neo4J: Static Got Android Node with sha256: {}'.format(datadict['sha256'])

    create_list_nodes_rels(graph, tx, na, 'Intent', datadict['intents'], 'ACTION_WITH_INTENT')
    # TODO Difference api/app permissions
    # TODO Permissions could be duplicates and cause an error, since the changes have not been committed yet -> No differentiation between them yet -> mege them
    #create_list_nodes_rels(graph, tx, na, 'Permission', datadict['api_permissions'], 'USES_PERMISSION')
    permissions = set(datadict['app_permissions'])
    permissions |= set(datadict['api_permissions'])
    create_list_nodes_rels(graph, tx, na, 'Permission', permissions, 'USES_PERMISSION')
    create_list_nodes_rels(graph, tx, na, 'URL', datadict['urls'], 'CONTAINS_URL')
    create_list_nodes_rels(graph, tx, na, 'API_Call', datadict['interesting_calls'], 'CALLS')
    create_list_nodes_rels(graph, tx, na, 'DEX_File', datadict['included_files_src'], 'INCLUDES_FILE_SRC')
    create_list_nodes_rels(graph, tx, na, 'Activity', datadict['activities'], 'ACTIVITY')
    create_list_nodes_rels(graph, tx, na, 'Feature', datadict['features'], 'FEATURE')
    create_list_nodes_rels(graph, tx, na, 'Provider', datadict['providers'], 'PROVIDER')
    create_list_nodes_rels(graph, tx, na, 'Service_Receiver', datadict['s_and_r'], 'SERVICE_RECEIVER') # TODO split s_and_r
    create_list_nodes_rels(graph, tx, na, 'Detected_Ad_Networks', datadict['detected_ad_networks'], 'DETECTED_AD_NETWORK')
    create_list_nodes_rels(graph, tx, na, 'Networks', datadict['networks'], 'NETWORK')
    create_list_nodes_rels(graph, tx, na, 'Package_Name', [ datadict['package_name']], 'PACKAGE_NAME')
    create_list_nodes_rels(graph, tx, na, 'SDK_Version_Target', [ datadict['sdk_version_target']], 'SDK_VERSION_TARGET')
    create_list_nodes_rels(graph, tx, na, 'SDK_Version_Min', [ datadict['sdk_version_min']], 'SDK_VERSION_MIN')
    create_list_nodes_rels(graph, tx, na, 'SDK_Version_Max', [ datadict['sdk_version_max']], 'SDK_VERSION_MAX')
    create_list_nodes_rels(graph, tx, na, 'App_Name', [ datadict['app_name']], 'APP_NAME')
    #add_attribute(na, datadict, 'api_calls') # TODO List of lists don't work yet

    # TODO SocketTimeout - takes too long?
    if misc_config.ENABLE_ZIPFILE_HASHING:
        # Add Nodes and Relationships with more than 1 attribute
        included_files = []
        included_files_attrdicts = []
        for fileinzip, attrdict in datadict['included_files'].items():
            included_files.append(fileinzip)
            included_files_attrdicts.append(attrdict)

        # TODO  Somehow higher O than Dex and pretty slow
        create_list_nodes_rels(graph, tx, na, 'File', included_files, 'INCLUDES_FILE', attributes=included_files_attrdicts, nodematchkey='md5', upper=True)

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

    # Create Certificate Node
    nc = Node('Certificate')
    add_attribute(nc, certdict, 'IssuerC')
    add_attribute(nc, certdict, 'IssuerCN')
    add_attribute(nc, certdict, 'IssuerDN')
    add_attribute(nc, certdict, 'IssuerE')
    add_attribute(nc, certdict, 'IssuerL')
    add_attribute(nc, certdict, 'IssuerO')
    add_attribute(nc, certdict, 'IssuerOU')
    add_attribute(nc, certdict, 'IssuerS')
    add_attribute(nc, certdict, 'SubjectC')
    add_attribute(nc, certdict, 'SubjectCN')
    add_attribute(nc, certdict, 'SubjectDN')
    add_attribute(nc, certdict, 'SubjectE')
    add_attribute(nc, certdict, 'SubjectKeyId')
    add_attribute(nc, certdict, 'SubjectL')
    add_attribute(nc, certdict, 'SubjectO')
    add_attribute(nc, certdict, 'SubjectOU')
    add_attribute(nc, certdict, 'SubjectS')
    add_attribute(nc, certdict, 'Rfc822Name')
    add_attribute(nc, certdict, 'SerialNumber')
    add_attribute(nc, certdict, 'Sha1Thumbprint', regex=r_sha1, upper=True)
    add_attribute(nc, certdict, 'validFromStr')
    add_attribute(nc, certdict, 'validToStr')
    add_attribute(nc, certdict, 'Version')
    tx.create(nc)
    print 'Neo4J: Created Certificate Node with Sha1Thumbprint: {}'.format(certdict['Sha1Thumbprint'])

    # Create SIGNED_WITH Relationship between Android Application and Certificate
    r = Relationship(na, 'SIGNED_WITH', nc)
    tx.create(r)

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
    if 'virustotal' in datadict:
        for antivirus, resultdict in datadict['virustotal']['scans'].items():
            if not resultdict['result']: continue # Skip null results
            create_list_nodes_rels(graph, tx, na, 'Antivirus', [resultdict['result']], 'ANTIVIRUS')

    tx.commit()
