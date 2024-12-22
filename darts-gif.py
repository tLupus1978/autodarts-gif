import os
import sys
from pathlib import Path
import platform
import random
import argparse
from urllib.parse import quote, unquote
import threading
import logging
import time
import json
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning) 
from flask import Flask, render_template, send_from_directory
from bs4 import BeautifulSoup
from queue import Queue
import tkinter as tk
from PIL import Image, ImageTk, ImageSequence
from PIL.Image import Resampling
import requests
from websocket_server import WebsocketServer
import socketio



sh = logging.StreamHandler()
sh.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
sh.setFormatter(formatter)
logger=logging.getLogger()
logger.handlers.clear()
logger.setLevel(logging.INFO)
logger.addHandler(sh)

app = Flask(__name__)
main_directory = os.path.dirname(os.path.realpath(__file__))

http_session = requests.Session()
http_session.verify = False
sio = socketio.Client(http_session=http_session, logger=True, engineio_logger=True)



VERSION = '1.1.0'

DEFAULT_HOST_IP = '0.0.0.0'
DEFAULT_WEB_PORT = '5001'

BOGEY_NUMBERS = [169, 168, 166, 165, 163, 162, 159]
SUPPORTED_CRICKET_FIELDS = [15, 16, 17, 18, 19, 20, 25]
SUPPORTED_GAME_VARIANTS = ['X01', 'Cricket', 'Random Checkout']

FILENAME_RANDOM_IMAGE = "darts_random.gif"
IMAGE_PARAMETER_SEPARATOR = "|"
SUPPORTED_IMAGE_FORMATS = ['.gif', '.jpg', '.jpeg', '.png']
SITES = [
    'tenor.com',  
    'knowyourmeme.com'
]





def ppi(message, info_object = None, prefix = '\r\n'):
    logger.info(prefix + str(message))
    if info_object != None:
        logger.info(str(info_object))
    
def ppe(message, error_object):
    ppi(message)
    if DEBUG:
        logger.exception("\r\n" + str(error_object))

def check_paths(main_directory, media_path):
    errors = None
    try:
        main_directory = os.path.normpath(os.path.dirname(os.path.realpath(main_directory)))
        media_path = os.path.normpath(media_path)

        if os.path.relpath(media_path, main_directory)[:2] != '..':
            errors = 'MEDIA_PATH resides inside MAIN-DIRECTORY! It is not allowed!'

    except Exception as e:
        errors = f'Path validation failed: {e}'

    return errors



def create_image_path(filename):
    if MEDIA_PATH is not None:
        for file_format in SUPPORTED_IMAGE_FORMATS:
            full_filename = os.path.join(MEDIA_PATH, f"{filename}{file_format}")
            if os.path.exists(full_filename):
                return full_filename
    return filename

def parse_images_argument(images_argument, custom_duration_possible = True):
    if images_argument == None or images_argument == ["x"] or images_argument == ["X"]:
        return images_argument

    parsed_list = list()
    for image in images_argument:
        try:
            image_params = image.split(IMAGE_PARAMETER_SEPARATOR)
            path_to_file = image_params[0].strip().lower()
            custom_duration = 0
            if custom_duration_possible == True and len(image_params) == 2 and image_params[1].isdigit() == True:
                custom_duration = int(image_params[1])
                   
            state = {"file": create_image_path(path_to_file)}
            parsed_list.append((state, custom_duration))
        except Exception as e:
            ppe("Failed to parse event-configuration: ", e)
            continue
        
    if parsed_list == []:
        return images_argument
    
    return parsed_list   

def parse_score_area_images_argument(score_area_images_arguments):
    if score_area_images_arguments == None:
        return score_area_images_arguments

    area = score_area_images_arguments[0].strip().split('-')
    if len(area) == 2 and area[0].isdigit() and area[1].isdigit():
        return ((int(area[0]), int(area[1])), parse_images_argument(score_area_images_arguments[1:]))
    else:
        raise Exception(score_area_images_arguments[0] + ' is not a valid score-area')



def process_variant_x01(msg):
    global stop_display
    stop_display = True
    hide_image()

    if msg['event'] == 'darts-thrown':
        if msg['playerIsBot'] == 'True':
            ppi("Player is bot - skip")
            return
    
        val = str(msg['game']['dartValue'])
        if SCORE_IMAGES[val] != None:
            schedule_image(image_queue, val, SCORE_IMAGES[val], 'Darts-thrown: ' + val)
        else:
            area_found = False
            ival = int(val)
            for SAE in SCORE_AREA_IMAGES:
                if SCORE_AREA_IMAGES[SAE] != None:
                    ((area_from, area_to), AREA_IMAGES) = SCORE_AREA_IMAGES[SAE]
                    
                    if ival >= area_from and ival <= area_to:
                        schedule_image(image_queue, str(ival), AREA_IMAGES, 'Darts-thrown: ' + val)
                        area_found = True
                        break
            if area_found == False:
                ppi('Darts-thrown: ' + val + ' - NOT configured!')

    elif msg['event'] == 'darts-pulled':
        schedule_image_close()

    elif msg['event'] == 'busted' and BUSTED_IMAGES != None:
        if msg['playerIsBot'] == 'True':
            ppi("Player is bot - skip")
            return
        schedule_image(image_queue, 'busted', BUSTED_IMAGES, 'Busted!')

    elif msg['event'] == 'game-won' and GAME_WON_IMAGES != None:
        if HIGH_FINISH_ON != None and int(msg['game']['dartsThrownValue']) >= HIGH_FINISH_ON and HIGH_FINISH_IMAGES != None:
            schedule_image(image_queue, 'highfinish', HIGH_FINISH_IMAGES, 'Game-won - HIGHFINISH')
        else:
            schedule_image(image_queue, 'gameshot', GAME_WON_IMAGES, 'Game-won')

    elif msg['event'] == 'match-won' and MATCH_WON_IMAGES != None:
        if HIGH_FINISH_ON != None and int(msg['game']['dartsThrownValue']) >= HIGH_FINISH_ON and HIGH_FINISH_IMAGES != None:
            schedule_image(image_queue, 'highfinish', HIGH_FINISH_IMAGES, 'Match-won - HIGHFINISH')
        else:
            schedule_image(image_queue, 'matchshot', MATCH_WON_IMAGES, 'Match-won')

    elif msg['event'] == 'match-started':
        schedule_image_close()
        
    elif msg['event'] == 'game-started':
        schedule_image_close()
            

    
def on_open_client(client, server):
    ppi('NEW CLIENT CONNECTED: ' + str(client))

def on_left_client(client, server):
    ppi('CLIENT DISCONNECTED: ' + str(client))

def broadcast(data):
    def process(*args):
        global server
        server.send_message_to_all(json.dumps(data, indent=2).encode('utf-8'))
    t = threading.Thread(target=process)
    t.start()
    t.join()
   

def get_random_file(list):
    global last_image
    randImageFound = None
    if len(list) > 1:
        # more than 1 image in the list
        i = 0
        while i < 30:
            ppi(f"Fetching random image from '{list}' for '{i}'th time")
            # try x times to find an image which is not yet shown
            randImageFound = random.choice(list)
            i+=1
            if last_image.count(randImageFound) == 0:
                # image not yet shown - add to last_image list
                last_image.append(randImageFound)
                ppi(f"Found new random image '{randImageFound}'")
                break
    else:
        # one image in the list
        randImageFound = random.choice(list)
        last_image.append(randImageFound)
    ppi(f"Found image '{randImageFound}'")
    return randImageFound

def sanitize_tag(tag):
    tag = tag.replace(' ', '-')
    tag = quote(tag, safe="")
    # ppi(tag)
    return tag    
   
def get_random_image_url(tag):
    tag = sanitize_tag(tag)
    sites_tested = SITES.copy()

    image_url = None
    while(image_url is None and sites_tested != []):
        try:
            # Choose random website
            rand_site = random.choice(sites_tested)
            sites_tested.remove(rand_site)
            ppi(f"Fetching random image from '{rand_site}' with tag '{tag}'")
            
            # Fetch random image by random website
            if rand_site == 'tenor.com':
                site_url = 'https://tenor.com/search/{tag}-gifs'.format(tag=tag)
                response = requests.get(site_url)
                html_content = response.text
                soup = BeautifulSoup(html_content, 'html.parser')
                gif_divs = soup.find_all('div', {'class': 'Gif'})
                if gif_divs:
                    image_url_tag = random.choice(gif_divs).find('img')
                    image_url = image_url_tag.get('src') if image_url_tag else None

            elif rand_site == 'knowyourmeme.com':
                site_url = 'https://knowyourmeme.com/search?context=images&q=type%3Agif+{tag}'.format(tag=tag)
                response = requests.get(site_url)
                html_content = response.text
                soup = BeautifulSoup(html_content, 'html.parser')
                gif_divs = soup.find_all('div', {'class': 'item'})

                if gif_divs:
                    gif_div = random.choice(gif_divs)
                    image_url_tag = gif_div.find('img', {'class': ''})
                    image_url = image_url_tag.get('data-src') if image_url_tag else None

        except Exception as e:
            print("error fetching image", str(e))
            continue

    # ppi(f"Random-Image-URL: {image_url}")
    return image_url

def get_state(event, images_list):
    choice = get_random_file(images_list)

    tag = 'darts'
    if isinstance(choice, tuple) and choice[0]['file'].endswith(tuple(SUPPORTED_IMAGE_FORMATS)) == False:
        tag = choice[0]['file']
    else:
        return choice

    gif_url = get_random_image_url(tag)
    gif_filename = FILENAME_RANDOM_IMAGE
    if gif_url is not None:
        response = requests.get(gif_url)
        with open(gif_filename, "wb") as f:
            f.write(response.content)
    return ({'file': gif_filename}, 0)
    

def on_key(event):
    global stop_display
    stop_display = True

def show_image(image):
    try:
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        image_width, image_height = image.size
        scale = min(screen_width / image_width, screen_height / image_height)
        new_width = int(image_width * scale)
        new_height = int(image_height * scale)
        resized_image = image.resize((new_width, new_height), Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(resized_image)
        label.config(image=photo)
        label.image = photo
    except Exception as e:
        pass

def hide_image():
    if WEB > 0:
        mirror_clear = {
                "event": "mirror-clear"
            }
        broadcast(mirror_clear)

    if WEB == 0 or WEB == 2:
        root.withdraw()

def render_image(event_name, image_list, ptext, duration):
    def stop_check():
        global stop_display
        if stop_display:
            label.image=""
            hide_image()
            stop_display = False
            return True
        return False
    
    
    global stop_display

    (state, duration) = get_state(event_name, image_list)
    ppi(ptext + ' - IMAGE: ' + str(state))
    image_path = state["file"]

    if os.path.exists(image_path) == False:
        ppi(f"Image not found: {image_path}")
        return
    
    if WEB > 0:
        mirror = {
                "event": "mirror",
                "file": quote(image_path, safe="")
            }
        broadcast(mirror)

    
    
    image = Image.open(image_path)

    if WEB == 0 or WEB == 2:
        label.image=""
        root.deiconify()
        root.attributes("-fullscreen", True)
        root.attributes('-topmost', True)

    if image_path.lower().endswith(".gif"):
        frames = [(frame.copy(), frame.info['duration']) for frame in ImageSequence.Iterator(image)]
        current_frame = 0
        st = time.time()
        frame_start_time = st
        start_time = st
        frame_duration = frames[current_frame][1] / 1000
        next_frame_time = frame_start_time + frame_duration

        while True:
            if stop_check():
                break

            now = time.time()
            if now >= next_frame_time:
                if WEB == 0 or WEB == 2:
                    show_image(frames[current_frame][0])
                current_frame = (current_frame + 1) % len(frames)
                frame_duration = frames[current_frame][1] / 1000
                frame_start_time = now
                next_frame_time = frame_start_time + frame_duration

            if duration > 0 and now - start_time >= duration:
                hide_image()
                break

            time.sleep(0.001)

    else:
        if WEB == 0 or WEB == 2:
            show_image(image)

        if duration > 0:
            start_time = time.time()
            while (time.time() - start_time) < duration:
                if stop_check():
                    break
                time.sleep(0.1)
            hide_image()

def display_images(image_queue):
    global stop_display

    while True:
        event_name, image_list, ptext, duration = image_queue.get()
        if event_name is None:
            break

        render_image(event_name, image_list, ptext, duration)

def schedule_image_close():
    global stop_display

    if WEB > 0:
            mirror_clear = {
                    "event": "mirror-clear"
                }
            broadcast(mirror_clear)
    if WEB == 0 or WEB == 2:
        stop_display = True

def schedule_image(image_queue, event_name, image_list, ptext, duration=0):
    global stop_display
    stop_display = False
    image_queue.put((event_name, image_list, ptext, duration))




@sio.event
def connect():
    ppi('CONNECTED TO DATA-FEEDER ' + sio.connection_url)

@sio.event
def connect_error(data):
    if DEBUG:
        ppe("CONNECTION TO DATA-FEEDER FAILED! " + sio.connection_url, data)

@sio.event
def message(msg):
    try:
        # ppi(message)
        if('game' in msg and 'mode' in msg['game']):
            mode = msg['game']['mode']
            if mode == 'X01' or mode == 'Cricket' or mode == 'Random Checkout':
                process_variant_x01(msg)
            # elif mode == 'Cricket':
            #     process_match_cricket(msg)

    except Exception as e:
        ppe('DATA-FEEDER Message failed: ', e)

@sio.event
def disconnect():
    ppi('DISCONNECTED FROM DATA-FEEDER ' + sio.connection_url)


def connect_data_feeder():
    try:
        server_host = CON.replace('ws://', '').replace('wss://', '').replace('http://', '').replace('https://', '')
        server_url = 'ws://' + server_host
        sio.connect(server_url, transports=['websocket'])
    except Exception:
        try:
            server_url = 'wss://' + server_host
            sio.connect(server_url, transports=['websocket'], retry=True, wait_timeout=3)
        except Exception:
            pass





@app.route('/')
def index():
    return render_template('index.html', host=DEFAULT_HOST_IP)

@app.route('/images/<path:file_id>', methods=['GET'])
def file(file_id):
    file_id = unquote(file_id)
    file_path = file_id
    if os.name == 'posix':  # Unix/Linux/MacOS
        directory = '/' + os.path.dirname(file_path)
    else:  # Windows
        directory = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    return send_from_directory(directory, file_name)

def start_websocket_server(host, port):
    global server
    server = WebsocketServer(host=host, port=port, loglevel=logging.ERROR)
    server.set_fn_new_client(on_open_client)
    server.set_fn_client_left(on_left_client)
    server.run_forever()

def start_flask_app(host, port):
    app.run(host=host, port=port, debug=False)



if __name__ == "__main__":

    ap = argparse.ArgumentParser()
    ap.add_argument("-CON", "--connection", default="127.0.0.1:8079", required=False, help="Connection to data feeder")
    ap.add_argument("-MP", "--media_path", required=False, default=None, help="Absolute path to your media folder")
    ap.add_argument("-HFO", "--high_finish_on", type=int, choices=range(1, 171), default=None, required=False, help="Individual score for highfinish")
    ap.add_argument("-HF", "--high_finish_images", default=None, required=False, nargs='*', help="image-definition when high-finish occurs")
    ap.add_argument("-G", "--game_won_images", default=None, required=False, nargs='*', help="image-definition when game won occurs")
    ap.add_argument("-M", "--match_won_images", default=None, required=False, nargs='*', help="image-definition when match won occurs")
    ap.add_argument("-B", "--busted_images", default=None, required=False, nargs='*', help="image-definition when bust occurs")
    for v in range(0, 181):
        val = str(v)
        ap.add_argument("-S" + val, "--score_" + val + "_images", default=None, required=False, nargs='*', help="WLED image-definition for score " + val)
    for a in range(1, 13):
        area = str(a)
        ap.add_argument("-A" + area, "--score_area_" + area + "_images", default=None, required=False, nargs='*', help="WLED image-definition for score-area")
    ap.add_argument("-WEB", "--web_gif", required=False, type=int, choices=range(0, 3), default=0, help="If '1' the application will host an web-endpoint, '2' it will do '1' and core display-functionality.")
    ap.add_argument("-WEBP", "--web_gif_port", required=False, type=int, default=DEFAULT_WEB_PORT, help="Web-Port")
    ap.add_argument("-DEB", "--debug", type=int, choices=range(0, 2), default=False, required=False, help="If '1', the application will output additional information")

    args = vars(ap.parse_args())

    MEDIA_PATH = None
    if args['media_path'] is not None:
        MEDIA_PATH = Path(args['media_path'])
    CON = args['connection']
    HIGH_FINISH_ON = args['high_finish_on']
    WEB = args['web_gif']
    WEB_PORT = args['web_gif_port']
    DEBUG = args['debug']

    GAME_WON_IMAGES = parse_images_argument(args['game_won_images'])
    MATCH_WON_IMAGES = parse_images_argument(args['match_won_images'])
    BUSTED_IMAGES = parse_images_argument(args['busted_images'])
    HIGH_FINISH_IMAGES = parse_images_argument(args['high_finish_images'])
    
    SCORE_IMAGES = dict()
    for v in range(0, 181):
        parsed_score = parse_images_argument(args["score_" + str(v) + "_images"])
        SCORE_IMAGES[str(v)] = parsed_score
        # ppi(parsed_score)
    SCORE_AREA_IMAGES = dict()
    for a in range(1, 13):
        parsed_score_area = parse_score_area_images_argument(args["score_area_" + str(a) + "_images"])
        SCORE_AREA_IMAGES[a] = parsed_score_area
        # ppi(parsed_score_area)


    
    global stop_display
    stop_display = False 

    last_image = []


    if DEBUG:
        ppi('Started with following arguments:')
        ppi(json.dumps(args, indent=4))

    osType = platform.system()
    osName = os.name
    osRelease = platform.release()
    ppi('\r\n', None, '')
    ppi('##########################################', None, '')
    ppi('       WELCOME TO DARTS-GIF', None, '')
    ppi('##########################################', None, '')
    ppi('VERSION: ' + VERSION, None, '')
    ppi('RUNNING OS: ' + osType + ' | ' + osName + ' | ' + osRelease, None, '')
    ppi('SUPPORTED GAME-VARIANTS: ' + " ".join(str(x) for x in SUPPORTED_GAME_VARIANTS), None, '')
    ppi('DONATION: bitcoin:bc1q8dcva098rrrq2uqhv38rj5hayzrqywhudvrmxa', None, '')
    ppi('\r\n', None, '')

    path_status = check_paths(__file__, MEDIA_PATH)
    if path_status is not None: 
        ppi('Please check your arguments: ' + path_status)
        sys.exit()  

    try:
        connect_data_feeder()

        root = tk.Tk()
        root.configure(bg='black')
        root.bind("<KeyPress>", on_key)
        root.bind("<Button-1>", on_key) 
        
        label = tk.Label(root, bg='black')
        label.pack()

        image_queue = Queue()
        display_thread = threading.Thread(target=display_images, args=(image_queue,))

        if WEB > 0:
            websocket_server_thread = threading.Thread(target=start_websocket_server, args=(DEFAULT_HOST_IP, 8039))
            websocket_server_thread.start()
            flask_app_thread = threading.Thread(target=start_flask_app, args=(DEFAULT_HOST_IP, WEB_PORT))
            flask_app_thread.start()

        display_thread.start()
        
        root.withdraw()
        root.mainloop()

        if WEB > 0:
            websocket_server_thread.join()
            flask_app_thread.join() 


    except Exception as e:
        ppe("Connect failed: ", e)



time.sleep(30)