#!/usr/bin/env python
from flask import Flask, render_template, Response, send_from_directory
import picamera
from replayCircularIO import BoundedPiCameraCircularIO
from base_camera import BaseCamera
import requests
import time
import xml.etree.ElementTree as ET
import datetime
import queue
import collections
import os
import threading
import logging
import subprocess

base_url=os.getenv('base_url','https://localhost/derbynet/')
action_cmd='action.php'
username=os.getenv('username','Photo')
password=os.getenv('password','')
qCmd = queue.Queue()
ReplayData = collections.namedtuple('ReplayData', ['CMD', 'DATA'])
fps=int(os.getenv('fps',30))

def check_ajax_return(response, reqtype):
    if response:
        xml=ET.fromstring(response.content)
        success = xml.find("success")
        if success is not None:
            return True
        failure = xml.find("failure")
        if failure is not None:
            print("Request {0} failed: {1}".format(reqtype, failure.text))
            return False
        else:
            print("Request {0} unknown response: {1}".format(reqtype, response.content))
            return False
    else:
        print("Request {0} http error {1}: {2}".format(reqtype, response.status_code, response.reason))

def login():
    s = requests.Session()
    r = s.post(base_url+action_cmd,
                data = {'action':'login',
                        'username':username,
                        'password':password
                        },
                timeout=5.0)
    if not(check_ajax_return(r, "login")):
        return None
    return s

def replay_response_thread(qCmd,ReplayData):
    s = requests.Session()
    while True:
        try:
            #print('Request')
            r = s.post(base_url+action_cmd,
                        data = {'action':'replay-message',
                                'status':'1',
                                'finished-replay':'0'
                                },
                        timeout=5.0)
            xml=ET.fromstring(r.content)
            replaymsgs=xml.findall('replay-message')
            for replaymsg in replaymsgs:
                parts = replaymsg.text.split(' ')
                print('replay-message')
                print(parts)
                if parts[0]=='START':
                    recName='{0}-{1}.h264'.format(parts[1],datetime.datetime.now().strftime("%y%m%d_%H%M%S"))
                    qCmd.put(ReplayData('START',recName))
                elif parts[0]=='REPLAY':
                    skipBack=min(float(parts[1]),8.0)
                    qCmd.put(ReplayData('REPLAY',skipBack))
        except:
            pass
def camera_thread(qCmd,ReplayData,camera):
    print('Logging In to Derbynet')
    while True:
        s = login()
        if s is not None:
            break
        time.sleep(1.0)
    print('Camera Thread Started')
    stream = BoundedPiCameraCircularIO(camera, seconds=10)
    camera.start_recording(stream, format='h264', intra_period=1)
    time.sleep(2) #wait for camera to warm up
    fName='test.h264' #Initial file
    print('Camera Loop Started')
    try:
        while True:
            #print('Camera Loop')
            camera.wait_recording(0)
            try:
                cmd=qCmd.get(timeout=1.0)
                print('CMD: {0}, {1}'.format(cmd.CMD,cmd.DATA))
                if cmd.CMD == 'START':
                    fName=cmd.DATA
                elif cmd.CMD=='REPLAY':
                    # Keep recording for 2 seconds and only then write the
                    # stream to disk
                    now = camera.timestamp
                    tsStart = now-1e6*float(cmd.DATA)
                    postTriggerSec=1.0
                    tsEnd = now+1e6*postTriggerSec
                    print('start timestamp: {0}'.format(tsStart))
                    print('end timestamp: {0}'.format(tsEnd))
                    camera.wait_recording(1.5)
                    fName_raw=os.path.join('/tmp/',fName)
                    first,last = stream.copy_to_bounded(fName_raw,tsStart,tsEnd)
                    print('TS: {0}, {1}'.format(first.timestamp,last.timestamp))
                    fName_mp4 = os.path.join('/tmp/','{0}.mp4'.format(os.path.splitext(fName)[0]))
                    command = "/usr/bin/MP4Box -add '{1}' -fps {0} '{2}'".format(fps,fName_raw,fName_mp4)
                    try:
                        output = subprocess.check_output(command, stderr=subprocess.STDOUT,shell=True)
                        os.remove(fName_raw)
                        r = s.post(base_url+action_cmd, 
                                    data = {'action':'video.upload'
                                            },
                                    files = {'video':open(fName_mp4, 'rb')},
                                    timeout=10.0)
                        if check_ajax_return(r, "upload"):
                            print('File uploaded: {0}'.format(fName_mp4))
                            os.remove(fName_mp4)
                    except subprocess.CalledProcessError as e:
                        print('FAIL:\ncmd:{}\noutput:{}'.format(e.cmd, e.output),flush=True)
            except queue.Empty:
                pass
    finally:
        camera.stop_recording()

camera = picamera.PiCamera(
            resolution=(640, 480),
            framerate=fps,
            clock_mode='raw'
        )

app = Flask(__name__)



@app.route('/')
def index():
    """Video streaming home page."""
    return render_template('index.html')


def gen(camera):
    """Video streaming generator function."""
    while True:
        frame = camera.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@app.route('/video_feed')
def video_feed():
    """Video streaming route. Put this in the src attribute of an img tag."""
    return Response(gen(BaseCamera(camera)),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/css/<path:filename>')
def cssRoute(filename):
    return send_from_directory('/app/css', filename, conditional=True)

@app.route('/img/<path:filename>')
def imgRoute(filename):
    return send_from_directory('/app/img', filename, conditional=True)

gunicorn_logger = logging.getLogger('gunicorn.error')
app.logger.handlers = gunicorn_logger.handlers
app.logger.setLevel(gunicorn_logger.level)

ct=threading.Thread(target=camera_thread,kwargs={'qCmd':qCmd,
                                                  'ReplayData':ReplayData,
                                                  'camera':camera})
rt=threading.Thread(target=replay_response_thread,kwargs={'qCmd':qCmd,
                                                  'ReplayData':ReplayData})
rt.start()
ct.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', threaded=True)
