import math
import json
import time
import regex
import openai
import os

from dotenv import load_dotenv
from json import JSONDecodeError
from flask import Flask, request, Response
from flask_cors import CORS
from flask_socketio import SocketIO, emit

path_prefix = '/var/www/Tsde_polling_api/Tsde_polling_api/'

print('AAAAAAAAAAAAAAAAAAAAAA')
print(os.getcwd())

load_dotenv(path_prefix + ".env")

OPENAI_KEY = os.getenv("OPENAI_KEY")
NEXT_ROUND_KEY = os.getenv("NEXT_ROUND_KEY")
MAX_PROMPT_LEN = 300
MIN_PROMPT_LEN = 10
MAX_AUTHOR_LEN = 20
DB_PATH = os.getenv('DB_PATH')
generator_command = os.getenv('GEN_CMD')
initial_data_path = os.getenv('INIT_DATA_PATH')

object_classes = ['Safe', 'Euclid', 'Keter', 'Thaumiel']

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

openai.api_key = OPENAI_KEY
print("connected to openAI")

last_scp_str = ""
with open(path_prefix + "last.txt", "r", encoding='utf-8') as f:
    last_scp_str = f.read().rstrip()

with open(path_prefix + 'current_scp.txt') as f:
    scp_number = int(f.read().rstrip())

# Set initial variable with savec file or with initial value otherwise

try:
    with open(path_prefix + initial_data_path, "r") as f:
        params = json.load(f)
except FileNotFoundError:
    params = dict(next_time=time.time() + 3600,
                  poll=[],
                  votes=dict(),
                  submitted_ips_count=dict()
                  )

if params['next_time'] < time.time():
    print('reseted')
    params['next_time'] = time.time() + 3600

next_time = params['next_time']
poll = params['poll']
votes = params['votes']
submitted_ips_count = params['submitted_ips_count']


def getSafetyLabel(text, username):
    content_to_classify = text

    response = openai.Completion.create(
        engine="content-filter-alpha",
        prompt="<|endoftext|>"+content_to_classify+"\n--\nLabel:",
        temperature=0,
        max_tokens=1,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        logprobs=10,
        user=username
    )

    output_label = response["choices"][0]["text"]

    # This is the probability at which we evaluate that a "2" is likely real
    # vs. should be discarded as a false positive
    toxic_threshold = -0.355

    if output_label == "2":
        # If the model returns "2", return its confidence in 2 or other output-labels
        logprobs = response["choices"][0]["logprobs"]["top_logprobs"][0]

        # If the model is not sufficiently confident in "2",
        # choose the most probable of "0" or "1"
        # Guaranteed to have a confidence for 2 since this was the selected token.
        if logprobs["2"] < toxic_threshold:
            logprob_0 = logprobs.get("0", None)
            logprob_1 = logprobs.get("1", None)

            # If both "0" and "1" have probabilities, set the output label
            # to whichever is most probable
            if logprob_0 is not None and logprob_1 is not None:
                if logprob_0 >= logprob_1:
                    output_label = "0"
                else:
                    output_label = "1"
            # If only one of them is found, set output label to that one
            elif logprob_0 is not None:
                output_label = "0"
            elif logprob_1 is not None:
                output_label = "1"

            # If neither "0" or "1" are available, stick with "2"
            # by leaving output_label unchanged.

    # if the most probable token is none of "0", "1", or "2"
    # this should be set as unsafe
    if output_label not in ["0", "1", "2"]:
        output_label = "2"

    return output_label


def is_scpid_legit(id_scp):
    if id_scp.isdigit():
        id_scp = int(id_scp)
        if id_scp < 9000 or id_scp > scp_number:
            return False
        else:
            return True
    else:
        return False


@app.route('/', methods=['GET'])
def main():
    return "gpt scp api live and running"


@app.route('/next_round/', methods=['GET'])
def next_round():
    global scp_number
    global poll
    global votes
    global submitted_ips_count
    global next_time
    global last_scp_str

    k = request.args.get('key')
    nt = request.args.get('next_time')

    if k == NEXT_ROUND_KEY:
        poll = []
        votes = dict()
        submitted_ips_count = dict()
        next_time = int(nt)
        scp_number += 1

        # save scp number
        with open(path_prefix + 'current_scp.txt', 'w') as f:
            f.write(str(scp_number+1))

        with open(path_prefix + "last.txt", "r", encoding='utf-8') as f:
            # f.write()
            last_scp_str = f.read().rstrip()

        socketio.emit('next_round', {
            'scp_desc': last_scp_str,
            'next_time': str(math.trunc(next_time * 1000))[0:-2] + "00"
        }, broadcast=True)

        return Response(status=200)

    return Response(status=403)


@app.route('/get_poll/', methods=['GET'])
def get_poll():
    if len(poll) == 0:
        return Response(status=204)

    return {'poll': poll}


@app.route('/upvote/')
def upvote():
    ip = request.remote_addr
    id_scp = request.args.get('id')

    if is_scpid_legit(id_scp):
        id_scp = int(id_scp)
    else:
        return Response(response="not a valid id", status=412)

    try:
        # open file
        with open(path_prefix + './upvotes.json', 'r') as json_file:
            data = json.load(json_file)
    except (FileNotFoundError, JSONDecodeError) as e:
        # file does not exist, create it
        data = dict()

    if id_scp in data:
        if ip not in data[id_scp]["ips"]:
            data[id_scp]["n_upvotes"] += 1
            data[id_scp]["ips"].append(ip)
        else:
            return Response(response="already voted", status=414)
    else:
        data[id_scp] = {
            "n_upvotes": 1,
            "ips": [ip]
        }

    with open(path_prefix + 'upvotes.json', 'w') as outfile:
        json.dump(data, outfile)

    return Response(response="upvote counted", status=200)


@app.route('/get_upvotes/', methods=['GET'])
def get_upvotes():
    try:
        # open file
        with open(path_prefix + './upvotes.json', 'r') as json_file:
            data = json.load(json_file)
    except (FileNotFoundError, JSONDecodeError) as e:
        # file does not exist, create it
        data = dict()

    return data


@app.route('/vote/', methods=['GET'])
def vote():
    ip = request.remote_addr

    # if already voted
    if ip in votes.keys():
        return Response(status=403)

    # gets vote
    n = request.args.get('n')

    # if out of bounds
    if n.isdigit():
        n = int(n)
        if(n >= len(poll) or n < 0):
            return Response(status=412)
    else:
        return Response(status=412)

    # count vote
    poll[n]['votes'] += 1
    votes[ip] = n

    return Response(status=200)


@app.route('/add_prompt/', methods=['GET'])
def add_prompt():
    global submitted_ips_count

    ip = request.remote_addr

    # if ip has already submitted one prompt
    if ip in submitted_ips_count.keys():
        if submitted_ips_count[ip] >= 3:
            return Response(response="You can submit a maximum of three prompts per round", status=429)
    else:
        submitted_ips_count[ip] = 0

    prompt = request.args.get('prompt')
    # check prompt length
    if len(prompt) > MAX_PROMPT_LEN:
        return Response(response="prompt is too long", status=412)
    if len(prompt) <= MIN_PROMPT_LEN:
        return Response(response="prompt is too short", status=412)

    # prompt_filtered = regex.match(r'[\p{Latin} !?.-]+', prompt).group(0) # remove all non latin + espace + ponctioation char
    # if prompt_filtered != prompt:
    #     return Response(response="prompt contains invalid characters", status=412)

    author = request.args.get('author')
    # check author lenght
    if len(author) > MAX_AUTHOR_LEN:
        return Response(response="author is too long", status=412)
    if len(author) <= 0:
        return Response(response="author is too long", status=412)

    nsfw = request.args.get('nsfw')
    # check if nsfw is boolean:
    if not(nsfw == 'true' or nsfw == 'false'):
        return Response(response="nsfw is not bool", status=412)

    scp_class = request.args.get('class')
    # check if scp_class is a digit
    if scp_class.isdigit():
        scp_class = int(scp_class)
        if scp_class > 3 or scp_class < 0:
            return Response(response="class number is not included between 0 (Safe) and 3 (Thaumiel)", status=412)
    else:
        return Response(response="not a number", status=412)

    # check if prompt is sfw or nsfw
    if getSafetyLabel(prompt, author) == "2":
        return Response(response="The prompt was flagged", status=412)

    submission = {
        'prompt': "SCP-" + str(scp_number) + " is " + prompt,
        'scpClass': object_classes[scp_class],
        'votes': 0,
        'index': len(poll),
        'author': author,
        'nsfw': nsfw
    }

    poll.append(submission)

    # broadcast to all clients
    socketio.emit('new_prompt', {'prompt': submission}, broadcast=True)

    submitted_ips_count[ip] += 1
    return Response(response="submission has been added!", status=200)


@app.route('/last_scp_desc/',  methods=['GET'])
def last_scp_desc():

    with open(path_prefix + "last.txt", "r", encoding='utf-8') as f:
        last_scp_str = f.read()

    return str(last_scp_str)


@app.route('/current_scp_number/', methods=['GET'])
def current_scp_number():
    return str(scp_number)


@app.route('/next_time/', methods=['GET'])
def next_time_():
    """Renvoie le next time au format de javascript"""
    return str(math.trunc(next_time * 1000))[0:-2] + "00"


@app.route('/save_data/', methods=['GET'])
def save_data():
    k = request.args.get('key')
    if k == NEXT_ROUND_KEY:
        with open(path_prefix + initial_data_path, "w") as f:
            data = dict(next_time=next_time,
                        poll=poll,
                        votes=votes,
                        submitted_ips_count=submitted_ips_count
                        )
            json.dump(data, f)

        with open(path_prefix + "current_scp.txt", "w") as f:
            f.write(str(scp_number))

    return "ok"


@app.route('/get_past_scp/', methods=['GET'])
def get_past_scp():
    idscp = request.args.get('file')

    if is_scpid_legit(idscp):
        idscp = int(idscp)
    else:
        return Response(response="not a valid id", status=412)

    with open(DB_PATH + 'SCP-' + str(idscp) + '-GPT.txt', 'r') as f:
        return f.read()


@app.route('/get_past_list/', methods=['GET'])
def get_past_list():
    with open(DB_PATH+'scp_list.csv', "r") as f:
        return f.read()


@app.route('/generate/')
def generate_scp():
    key = request.args.get('key')
    if key == NEXT_ROUND_KEY:
        os.system(generator_command)

        with open(path_prefix + initial_data_path, "w") as f:
            data = dict(next_time=next_time,
                        poll=[],
                        votes=dict(),
                        submitted_ips=[]
                        )

            json.dump(data, f)
        return 'ok'
    else:
        return 'ko'


@socketio.on('connect')
def test_connect():
    print('Client connected')


if __name__ == "__main__":
    socketio.run(app=app, host='0.0.0.0', port=45900, debug=True)
