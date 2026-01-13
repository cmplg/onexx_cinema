from flask import Flask, render_template, jsonify, request
from zeep import Client, helpers
from zeep.transports import Transport
from requests import Session
from requests.auth import HTTPBasicAuth
from datetime import datetime
import os

app = Flask(__name__)

# --- CONFIGURATION ONEXX ---
STUDIOS = [
    {"id": 1, "name": "TH 1", "ip": "10.201.22.14", "user": "manager", "pass": "password"},
    {"id": 2, "name": "TH 2", "ip": "10.201.22.24", "user": "manager", "pass": "password"},
    {"id": 3, "name": "TH 3", "ip": "10.201.22.34", "user": "manager", "pass": "password"},
]

WSDL_FOLDER = os.path.abspath("wsdls")
cached_sid = {}

def get_client(studio, wsdl_name):
    session = Session()
    session.auth = HTTPBasicAuth(studio['user'], studio['pass'])
    transport = Transport(session=session, timeout=4)
    wsdl_path = os.path.join(WSDL_FOLDER, f"{wsdl_name}.wsdl")
    client = Client(wsdl=wsdl_path, transport=transport)
    endpoint = f"http://{studio['ip']}:10000/dc/dcp/ws/v1/{wsdl_name}"
    client.service._binding_options['address'] = endpoint
    return client.service

def fetch_studio_status(studio):
    sid = cached_sid.get(studio['id'])
    res = {
        "studio_info": studio, "online": False,
        "playback": {
            "spl_title": "---", "cpl_title": "---", "state": "OFFLINE", 
            "spl_progress": 0, "cpl_progress": 0,
            "spl_pos": 0, "spl_dur": 0
        },
        "projector": {"lamp": "--", "dowser": "--"},
        "storage": {"fullness": 0},
        "system": {"hardware": "--", "temp": "--"},
        "scheduler": {"active": False}
    }
    try:
        if not sid:
            sid = get_client(studio, "SessionManagement").Login(username=studio['user'], password=studio['pass'])
            cached_sid[studio['id']] = sid
        res["online"] = True
        
        # 1. Playback & Dual Progress
        svc_show = get_client(studio, "ShowControl")
        pb = svc_show.GetShowStatus(sessionId=sid)
        res["playback"].update({
            "spl_title": getattr(pb, 'splTitle', 'No Playlist'),
            "cpl_title": getattr(pb, 'cplTitle', 'No Feature'),
            "state": getattr(pb, 'stateInfo', 'Stopped'),
            "spl_pos": getattr(pb, 'splPosition', 0),
            "spl_dur": getattr(pb, 'splDuration', 0),
            "spl_progress": round((getattr(pb, 'splPosition', 0) / getattr(pb, 'splDuration', 1) * 100), 1) if getattr(pb, 'splDuration', 0) > 0 else 0,
            "cpl_progress": round((getattr(pb, 'editPosition', 0) / getattr(pb, 'editDuration', 1) * 100), 1) if getattr(pb, 'editDuration', 0) > 0 else 0
        })
        
        # 2. Scheduler State
        svc_sch = get_client(studio, "ScheduleManagement")
        res["scheduler"]["active"] = (svc_sch.GetSchedulerStatus(sessionId=sid) == "Running")

        # 3. Storage & Sensors (IMB / Board Temp)
        try:
            svc_str = get_client(studio, "StorageManagement")
            sl = svc_str.GetStorageList(sessionId=sid)
            if sl: res["storage"]["fullness"] = sl[0]['fullness'] if isinstance(sl[0], dict) else getattr(sl[0], 'fullness', 0)
            
            svc_sens = get_client(studio, "Sensors")
            sensors = svc_sens.GetSensorList(sessionId=sid)
            for s in sensors:
                if 'temp' in str(s['sensorTitle']).lower():
                    res["system"]["temp"] = f"{s['sensorValue']}°C"
                    break
        except: pass

        # 4. Projector Info
        svc_ovr = get_client(studio, "SystemOverview")
        ovr = svc_ovr.GetSystemOverview(sessionId=sid)
        res["projector"] = {"lamp": getattr(ovr.projector, 'lamp', '--'), "dowser": getattr(ovr.projector, 'dowser', '--')}
        res["system"]["hardware"] = getattr(ovr.status, 'hardware', '--')

    except: cached_sid[studio['id']] = None
    return res

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/all_status')
def all_status(): return jsonify([fetch_studio_status(s) for s in STUDIOS])

@app.route('/api/content_library')
def content_library():
    all_cpls = {}
    for studio in STUDIOS:
        sid = cached_sid.get(studio['id'])
        if not sid: continue
        try:
            svc_cpl = get_client(studio, "CPLManagement")
            cpl_ids = helpers.serialize_object(svc_cpl.GetCplList(sessionId=sid))
            for c_id in cpl_ids[:25]:
                if c_id not in all_cpls:
                    info = svc_cpl.GetCplInfo(sessionId=sid, cplId=c_id)
                    all_cpls[c_id] = {
                        "title": getattr(info, 'contentTitleText', 'Unknown'),
                        "duration": f"{round(getattr(info, 'durationEdits', 0)/86400)} min",
                        "size": f"{round(getattr(info, 'cplSizeInBytes', 0)/(1024**3), 2)} GB",
                        "studios": [studio['name']],
                        "kdm": "Valid" if getattr(info, 'playable', True) else "No KDM"
                    }
                else: all_cpls[c_id]["studios"].append(studio['name'])
        except: pass
    return jsonify(list(all_cpls.values()))

@app.route('/api/playlists/<int:studio_id>')
def get_playlists(studio_id):
    studio = next((s for s in STUDIOS if s['id'] == studio_id), None)
    sid = cached_sid.get(studio_id)
    if not sid: return jsonify([])
    try:
        svc = get_client(studio, "SPLManagement")
        return jsonify(helpers.serialize_object(svc.GetSplList(sessionId=sid)))
    except: return jsonify([])

@app.route('/api/control/<int:studio_id>/<action>')
def control_playback(studio_id, action):
    studio = next((s for s in STUDIOS if s['id'] == studio_id), None)
    sid = cached_sid.get(studio_id)
    try:
        if action == "toggle_scheduler":
            status = request.args.get('status')
            svc = get_client(studio, "ScheduleManagement")
            svc.StartScheduler(sessionId=sid) if status == "on" else svc.StopScheduler(sessionId=sid)
        elif action.startswith("load_"):
            uuid = action.replace("load_", "")
            get_client(studio, "ShowControl").LoadShowAsset(sessionId=sid, splId=uuid)
        else:
            svc = get_client(studio, "ShowControl")
            if action == "play": svc.Play(sessionId=sid)
            elif action == "pause": svc.Pause(sessionId=sid)
            elif action == "eject": svc.Eject(sessionId=sid)
        return jsonify({"status": "success"})
    except: return jsonify({"status": "error"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)