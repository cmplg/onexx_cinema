import os
from zeep import Client
from requests import Session
from requests.auth import HTTPBasicAuth
from zeep.transports import Transport

# --- KONFIGURASI ---
IMS_IP = "10.201.22.14" 
USER = "manager"
PASS = "password" # MASUKKAN PASSWORD ASLI

session = Session()
session.auth = HTTPBasicAuth(USER, PASS)
transport = Transport(session=session, timeout=10)

def get_svc(wsdl_name):
    path = os.path.abspath(f"wsdls/{wsdl_name}.wsdl")
    client = Client(wsdl=path, transport=transport)
    url = f"http://{IMS_IP}:10000/dc/dcp/ws/v1/{wsdl_name}"
    return client.create_service('{http://www.doremilabs.com/dc/dcp/ws/v1}' + wsdl_name + '_v1_0_SOAPBinding', url)

try:
    # 1. Login
    sid = get_svc("SessionManagement").Login(username=USER, password=PASS)
    print(f"LOGIN SUKSES! SID: {sid}\n")

    # 2. Ambil List UUID
    svc_m = get_svc("MacroManagement")
    print("Mengambil daftar ID...")
    macro_ids = svc_m.GetMacroList(sessionId=sid)

    print("\n" + "="*60)
    print("HASIL PEMETAAN (COPAS SEMUA DI BAWAH INI):")
    print("="*60)

    for mid in macro_ids:
        try:
            # Sesuai gambar WSDL kamu: GetMacroInfo
            info = svc_m.GetMacroInfo(sessionId=sid, macroId=mid)
            # Ambil title dari response
            name = info['title'] if isinstance(info, dict) else info.title
            clean_key = name.lower().replace(" ", "_").replace(".", "_")
            print(f"    '{clean_key}': '{mid}',  # {name}")
        except Exception as e:
            print(f"    'unknown_{mid[-4:]}': '{mid}', # Gagal ambil nama")

    print("="*60)

except Exception as e:
    print(f"ERROR: {e}")