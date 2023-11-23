from lxml import etree
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import re
import glob
import json
from tqdm import tqdm

def parse_tei(xml_file_path):
    ns = {'tei': 'http://www.tei-c.org/ns/1.0', "xml":"http://www.w3.org/XML/1998/namespace"}
    tree = etree.parse(xml_file_path)
    root = tree.getroot()

    repository = root.find('.//tei:msIdentifier/tei:repository', namespaces=ns).text
    id_doc = root.find('.//tei:msIdentifier/tei:idno', namespaces=ns).text

    # Use the namespace in the XPath query and access title
    title = root.find('.//tei:msItem/tei:title', namespaces=ns).text

    lang = root.find('.//tei:msItem/tei:textLang', namespaces=ns).text

    # Find support information and extent
    support = " ".join([t.strip() for t in root.find('.//tei:supportDesc/tei:support', namespaces=ns).itertext()])
    extent = root.find('.//tei:supportDesc/tei:extent', namespaces=ns).text
    
    # Find origin date and place
    orig_date = root.find('.//tei:origin/tei:origDate', namespaces=ns).text
    orig_place = root.find('.//tei:origin/tei:origPlace', namespaces=ns)
    orig_place_key = orig_place.get("key")
    orig_place_text = orig_place.text
    
    # Find list of persons in letter and viaf key
    persons = root.findall('.//tei:listPerson/tei:person', namespaces=ns)
    pers_list = []
    for person in persons:
        ref = person.get("{http://www.w3.org/XML/1998/namespace}id")
        key = person.find("tei:persName", namespaces=ns).get("key")
        forename = person.find("tei:persName/tei:forename", namespaces=ns).text
        surname = person.find("tei:persName/tei:surname", namespaces=ns).text
        pers_list.append({"key":key, "ref":ref, "forename":forename, "surname":surname, "persName":forename+" "+surname})
    
    # Find list of places in letter and GeoNames key
    places = root.findall('.//tei:listPlace/tei:place', namespaces=ns)
    place_list = []
    for place in places:
        ref = place.get("{http://www.w3.org/XML/1998/namespace}id")
        key = place.find("tei:placeName", namespaces=ns).get("key")
        name = place.find("tei:placeName", namespaces=ns).text
        place_list.append({"key":key, "ref":ref, "placeName":name})

    
    # Extract correspondents
    correspondents = root.findall('.//tei:correspDesc/tei:correspAction', namespaces=ns)
    for correspondent in correspondents:
        if correspondent.get("type")=="sent":
            sender_name = correspondent.find("tei:persName", namespaces=ns).text
            sender_key = correspondent.find("tei:persName", namespaces=ns).get("key")
        if correspondent.get("type")=="received":
            receiver_name = correspondent.find("tei:persName", namespaces=ns).text
            receiver_key = correspondent.find("tei:persName", namespaces=ns).get("key") 
    try:
        sender = sender_name+" ("+sender_key+")"
        receiver = receiver_name+" ("+receiver_key+")" 
    except:
        sender = ""
        receiver=""

    doc_txt = " ".join([t.strip() for t in root.find('.//tei:text/tei:body', namespaces=ns).itertext()])
    output = {"id_doc":id_doc, 
              "repo":repository, 
              "title":title,
              "lang":lang,
              "support":support,
              "extent":extent,
              "orig_date":orig_date,
              "orig_place":orig_place_text + " ("+orig_place_key+")",
              "sender": sender,
              "receiver":receiver,
              "text":doc_txt,
              "persons":pers_list,
              "places":place_list
            }
    return output


def extract_triplets_typed(text):
    triplets = []
    relation = ''
    text = text.strip()
    current = 'x'
    subject, relation, object_, object_type, subject_type = '','','','',''

    for token in text.replace("<s>", "").replace("<pad>", "").replace("</s>", "").replace("tp_XX", "").replace("__en__", "").split():
        if token == "<triplet>" or token == "<relation>":
            current = 't'
            if relation != '':
                triplets.append({'head': subject.strip(), 'head_type': subject_type, 'type': relation.strip(),'tail': object_.strip(), 'tail_type': object_type})
                relation = ''
            subject = ''
        elif token.startswith("<") and token.endswith(">"):
            if current == 't' or current == 'o':
                current = 's'
                if relation != '':
                    triplets.append({'head': subject.strip(), 'head_type': subject_type, 'type': relation.strip(),'tail': object_.strip(), 'tail_type': object_type})
                object_ = ''
                subject_type = token[1:-1]
            else:
                current = 'o'
                object_type = token[1:-1]
                relation = ''
        else:
            if current == 't':
                subject += ' ' + token
            elif current == 's':
                object_ += ' ' + token
            elif current == 'o':
                relation += ' ' + token
    if subject != '' and relation != '' and object_ != '' and object_type != '' and subject_type != '':
        triplets.append({'head': subject.strip(), 'head_type': subject_type, 'type': relation.strip(),'tail': object_.strip(), 'tail_type': object_type})
    return triplets

# Load model and tokenizer
tokenizer = AutoTokenizer.from_pretrained("Babelscape/mrebel-large-32", tgt_lang="tp_XX") 
tokenizer._src_lang = "it_XX"
tokenizer.cur_lang_code_id = tokenizer.convert_tokens_to_ids("it_XX")
tokenizer.set_src_lang_special_tokens("it_XX")
model = AutoModelForSeq2SeqLM.from_pretrained("Babelscape/mrebel-large-32")
gen_kwargs = {
    "max_length": 256,
    "length_penalty": 0,
    "num_beams": 3,
    "num_return_sequences": 3,
    "forced_bos_token_id": None,
}


pbar = tqdm(total=41)

lst_of_dict = []
for tei_doc in glob.glob("xml_tei/*.txt"):
    xml_file_path = tei_doc
    data = parse_tei(xml_file_path)
    text = data["text"]
    model_inputs = tokenizer(text, max_length=256, padding=True, truncation=True, return_tensors = 'pt')
    generated_tokens = model.generate(
    model_inputs["input_ids"].to(model.device),
    attention_mask=model_inputs["attention_mask"].to(model.device),
    decoder_start_token_id = tokenizer.convert_tokens_to_ids("tp_XX"),
    **gen_kwargs,
)
    # Extract text
    decoded_preds = tokenizer.batch_decode(generated_tokens, skip_special_tokens=False)
    triples_set = set()
    # Extract triplets
    for sentence in decoded_preds:
        triples = extract_triplets_typed(sentence)
        for triple in triples:
            triple_string="<"+triple["head"]+"; "+triple["head_type"]+"> <"+triple["type"]+"> <"+triple["tail"]+"; "+triple["tail_type"]+">"
            triples_set.add(triple_string)
    triples_lst = list(triples_set)
    data["triples"]=triples_lst
    lst_of_dict.append(data)
    pbar.update(1)
pbar.close()

with open("test2.json", "w", encoding="utf-8") as f:
    json.dump(lst_of_dict, f, ensure_ascii=False, indent=4)
