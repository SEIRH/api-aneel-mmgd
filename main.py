from fastapi import FastAPI
from fastapi.responses import Response
import pandas as pd
import requests
import zipfile
import urllib3
import os
import tempfile
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings()
app = FastAPI()

@app.get("/")
def raiz():
    return {"status": "API da ANEEL rodando! Acesse /dados-pb para baixar o CSV da Paraíba."}

@app.get("/dados-pb")
def obter_dados_pb():
    url = "https://dadosabertos.aneel.gov.br/dataset/5e0fafd2-21b9-4d5b-b622-40438d40aba2/resource/b1bd71e7-d0ad-4214-9053-cbd58e9564a7/download/empreendimento-geracao-distribuida.zip"
    
    session = requests.Session()
    retry = Retry(connect=5, read=5, backoff_factor=1)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    # Cria uma pasta temporária no disco do Render para não usar a RAM
    with tempfile.TemporaryDirectory() as tmpdirname:
        zip_path = os.path.join(tmpdirname, "dados.zip")
        
        # 1. Baixa o arquivo em partes e salva no disco
        response = session.get(url, verify=False, stream=True)
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024): # Chunks de 1MB
                if chunk:
                    f.write(chunk)
                    
        # 2. Extrai o CSV do ZIP direto pro disco
        with zipfile.ZipFile(zip_path, 'r') as z:
            nome_arquivo = z.namelist()[0]
            csv_path = z.extract(nome_arquivo, tmpdirname)
            
        # 3. Lê o CSV em pedaços pequenos (chunks) para salvar memória
        df_pb_list = []
        chunk_iter = pd.read_csv(csv_path, sep=';', encoding='latin1', low_memory=False, chunksize=50000)
        
        for chunk in chunk_iter:
            # Filtra só a Paraíba neste pedaço pequeno e guarda
            pb_chunk = chunk[chunk['SigUF'] == 'PB']
            df_pb_list.append(pb_chunk)
            
        # 4. Junta todos os pedaços da Paraíba num arquivo só
        df_pb_final = pd.concat(df_pb_list, ignore_index=True)
        
        # Transforma o resultado final em CSV de texto
        csv_dados = df_pb_final.to_csv(index=False)
        
    # Quando o código sai do bloco 'with', a pasta temporária é apagada automaticamente!
    
    return Response(content=csv_dados, media_type="text/csv")
