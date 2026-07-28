# ==============================================================================
# API Intermediária ANEEL — Geração Distribuída (Filtrado para PB)
# ------------------------------------------------------------------------------
# Hospedagem recomendada : Render.com (free tier)
# Consumo no Power BI    : Web.Contents no Power Query (retorna CSV)
# Cache                  : Em disco, expira a cada 24 horas
# ==============================================================================

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
import pandas as pd
import requests
import zipfile
import urllib3
import os
import tempfile
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings()

app = FastAPI(
    title="API ANEEL - Geração Distribuída (PB)",
    description="Filtra e consolida dados de Geração Distribuída da ANEEL para consumo no Power BI.",
    version="2.0.0", # Versão otimizada para Disco e FileResponse
)

# ------------------------------------------------------------------------------
# Configurações
# ------------------------------------------------------------------------------
URL_ANEEL = "https://dadosabertos.aneel.gov.br/dataset/5e0fafd2-21b9-4d5b-b622-40438d40aba2/resource/b1bd71e7-d0ad-4214-9053-cbd58e9564a7/download/empreendimento-geracao-distribuida.zip"
ESTADO_ALVO = "PB"
CACHE_DURACAO_HORAS = 24
ARQUIVO_CACHE = "mmgd_pb.csv" # Salva no disco ao invés da RAM

# ------------------------------------------------------------------------------
# Controle de Cache
# ------------------------------------------------------------------------------
_cache: dict = {
    "expira_em": None,
    "ultima_atualizacao": None,
    "total_registros": 0,
    "erros": [],
}

def _cache_valido() -> bool:
    return (
        _cache["expira_em"] is not None
        and datetime.now() < _cache["expira_em"]
        and os.path.exists(ARQUIVO_CACHE)
    )

def _coletar_dados_aneel() -> None:
    erros = []
    
    session = requests.Session()
    retry = Retry(connect=5, read=5, backoff_factor=1)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    try:
        with tempfile.TemporaryDirectory() as tmpdirname:
            zip_path = os.path.join(tmpdirname, "dados.zip")
            
            # 1. Download do ZIP para o disco temporário (~130MB)
            response = session.get(URL_ANEEL, verify=False, stream=True, timeout=60)
            response.raise_for_status()
            
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        
            # 2 e 3. Lê o CSV DIRETO de dentro do ZIP
            df_pb_list = []
            with zipfile.ZipFile(zip_path, 'r') as z:
                nome_arquivo = z.namelist()[0]
                
                with z.open(nome_arquivo) as f_csv:
                    
                    chunk_iter = pd.read_csv(f_csv, sep=';', encoding='latin1', low_memory=False, chunksize=50000)
                    
                    for chunk in chunk_iter:
                        pb_chunk = chunk[chunk['SigUF'] == ESTADO_ALVO]
                        df_pb_list.append(pb_chunk)
                
            # 4. Consolida e SALVA NO DISCO
            if df_pb_list:
                df_final = pd.concat(df_pb_list, ignore_index=True)
                total = len(df_final)
                
                # utf-8-sig garante que o Power BI leia os acentos sem falhas
                df_final.to_csv(ARQUIVO_CACHE, index=False, encoding="utf-8-sig", sep=";")
            else:
                total = 0

    except Exception as e:
        total = 0
        erros.append(str(e))

    # Atualiza cache
    if total > 0 or os.path.exists(ARQUIVO_CACHE):
        _cache["expira_em"] = datetime.now() + timedelta(hours=CACHE_DURACAO_HORAS)
        _cache["ultima_atualizacao"] = datetime.now().isoformat()
        _cache["total_registros"] = total
    _cache["erros"] = erros


# ------------------------------------------------------------------------------
# Endpoints da API
# ------------------------------------------------------------------------------

@app.get("/", summary="Página Inicial")
def raiz():
    return {
        "status": "API ANEEL (PB) rodando perfeitamente!", 
        "instrucao": "Use o endpoint /dados-pb no Power BI para obter o CSV."
    }

@app.get(
    "/dados-pb",
    response_class=FileResponse,
    summary="Retorna CSV consolidado da Paraíba",
    description="Use este endpoint no Power BI via Web.Contents.",
)
def get_dados_pb():
    if not _cache_valido():
        _coletar_dados_aneel()

    if not os.path.exists(ARQUIVO_CACHE):
        return Response(
            content="Nenhum dado disponível. A conexão com a ANEEL pode ter falhado.",
            status_code=503,
            media_type="text/plain",
        )

    # Envia o arquivo direto do disco, desafogando a memória do servidor
    return FileResponse(
        path=ARQUIVO_CACHE,
        media_type="text/csv",
        filename="mmgd_pb.csv"
    )

@app.get("/colunas", summary="Lista as colunas disponíveis no dataset")
def get_colunas():
    if not _cache_valido():
        _coletar_dados_aneel()

    if not os.path.exists(ARQUIVO_CACHE):
        return Response(content="Nenhum dado disponível.", status_code=503)

    df = pd.read_csv(ARQUIVO_CACHE, sep=";", dtype=str, nrows=1)
    return {"colunas": list(df.columns)}

@app.get("/status", summary="Status do cache e da última coleta")
def get_status():
    return {
        "cache_valido": _cache_valido(),
        "ultima_atualizacao": _cache["ultima_atualizacao"],
        "expira_em": _cache["expira_em"].isoformat() if _cache["expira_em"] else None,
        "total_registros_pb": _cache["total_registros"],
        "tamanho_arquivo_mb": round(os.path.getsize(ARQUIVO_CACHE) / (1024 * 1024), 2) if os.path.exists(ARQUIVO_CACHE) else 0,
        "erros_na_ultima_coleta": _cache["erros"],
    }

@app.get("/atualizar", summary="Força recoleta imediata (ignora cache)")
def forcar_atualizacao():
    _coletar_dados_aneel()
    return {
        "mensagem": "Dados da ANEEL recoletados com sucesso.",
        "total_registros_pb": _cache["total_registros"],
        "erros": _cache["erros"],
    }
