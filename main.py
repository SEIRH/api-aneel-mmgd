from fastapi import FastAPI
from fastapi.responses import Response
import pandas as pd
import requests
import zipfile
import io
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings()
app = FastAPI()

@app.get("/dados-pb")
def obter_dados_pb():
    url = "https://dadosabertos.aneel.gov.br/dataset/5e0fafd2-21b9-4d5b-b622-40438d40aba2/resource/b1bd71e7-d0ad-4214-9053-cbd58e9564a7/download/empreendimento-geracao-distribuida.zip"
    
    session = requests.Session()
    retry = Retry(connect=5, read=5, backoff_factor=1)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    # Baixa em partes para evitar queda
    response = session.get(url, verify=False, stream=True)
    
    zip_buffer = io.BytesIO()
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            zip_buffer.write(chunk)
            
    # Extrai da memória
    with zipfile.ZipFile(zip_buffer) as z:
        nome_arquivo = z.namelist()[0]
        with z.open(nome_arquivo) as f:
            df = pd.read_csv(f, sep=';', encoding='latin1', low_memory=False)
            
    # Filtra a Paraíba
    df_pb = df[df['SigUF'] == 'PB']
    csv_dados = df_pb.to_csv(index=False)
    
    return Response(content=csv_dados, media_type="text/csv")
