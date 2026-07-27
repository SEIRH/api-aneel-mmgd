# ==============================================================================
# API Intermediária ANEEL — Geração Distribuída (Filtrado para PB)
# ------------------------------------------------------------------------------
# Hospedagem recomendada : Render.com (free tier)
# Consumo no Power BI    : Web.Contents no Power Query (retorna CSV)
# Cache                  : Em memória, expira a cada 24 horas
# ==============================================================================

from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse
import pandas as pd
import requests
import zipfile
import urllib3
import os
import tempfile
import io
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings()

app = FastAPI(
    title="API ANEEL - Geração Distribuída (PB)",
    description="Filtra e consolida dados de Geração Distribuída da ANEEL para consumo no Power BI.",
    version="1.0.1", # Versão atualizada contra estouro de disco
)

# ------------------------------------------------------------------------------
# Configurações
# ------------------------------------------------------------------------------
URL_ANEEL = "https://dadosabertos.aneel.gov.br/dataset/5e0fafd2-21b9-4d5b-b622-40438d40aba2/resource/b1bd71e7-d0ad-4214-9053-cbd58e9564a7/download/empreendimento-geracao-distribuida.zip"
ESTADO_ALVO = "PB"
CACHE_DURACAO_HORAS = 24

# ------------------------------------------------------------------------------
# Cache em memória
# ------------------------------------------------------------------------------
_cache: dict = {
    "csv_data": None,
    "expira_em": None,
    "ultima_atualizacao": None,
    "total_registros": 0,
    "erros": [],
}

def _cache_valido() -> bool:
    return (
        _cache["csv_data"] is not None
        and _cache["expira_em"] is not None
        and datetime.now() < _cache["expira_em"]
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
                        
            # 2 e 3. Lê o CSV DIRETO de dentro do ZIP, SEM extrair para o disco!
            df_pb_list = []
            with zipfile.ZipFile(zip_path, 'r') as z:
                nome_arquivo = z.namelist()[0]
                
                # Abre um stream de leitura do arquivo interno
                with z.open(nome_arquivo) as f_csv:
                    # O Pandas vai sugando as linhas de 50k em 50k direto de dentro do ZIP
                    chunk_iter = pd.read_csv(f_csv, sep=';', encoding='latin1', low_memory=False, chunksize=50000)
                    
                    for chunk in chunk_iter:
                        pb_chunk = chunk[chunk['SigUF'] == ESTADO_ALVO]
                        df_pb_list.append(pb_chunk)
                
            # 4. Consolida o resultado final (agora bem leve, só a Paraíba)
            if df_pb_list:
                df_final = pd.concat(df_pb_list, ignore_index=True)
                total = len(df_final)
                
                buf = io.StringIO()
                df_final.to_csv(buf, index=False, encoding="utf-8", sep=";")
                csv_str = buf.getvalue()
            else:
                csv_str = ""
                total = 0

    except Exception as e:
        csv_str = ""
        total = 0
        erros.append(str(e))

    # Atualiza cache
    if total > 0 or not _cache["csv_data"]:
        _cache["csv_data"] = csv_str
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
    response_class=PlainTextResponse,
    summary="Retorna CSV consolidado da Paraíba",
    description="Use este endpoint no Power BI via Web.Contents.",
)
def get_dados_pb():
    if not _cache_valido():
        _coletar_dados_aneel()

    if not _cache["csv_data"]:
        return Response(
            content="Nenhum dado disponível. A conexão com a ANEEL pode ter falhado.",
            status_code=503,
            media_type="text/plain",
        )

    return PlainTextResponse(
        content=_cache["csv_data"],
        media_type="text/plain; charset=utf-8",
    )

@app.get("/colunas", summary="Lista as colunas disponíveis no dataset")
def get_colunas():
    if not _cache_valido():
        _coletar_dados_aneel()

    if not _cache["csv_data"]:
        return Response(content="Nenhum dado disponível.", status_code=503)

    df = pd.read_csv(io.StringIO(_cache["csv_data"]), sep=";", dtype=str, nrows=1)
    return {"colunas": list(df.columns)}

@app.get("/status", summary="Status do cache e da última coleta")
def get_status():
    return {
        "cache_valido": _cache_valido(),
        "ultima_atualizacao": _cache["ultima_atualizacao"],
        "expira_em": _cache["expira_em"].isoformat() if _cache["expira_em"] else None,
        "total_registros_pb": _cache["total_registros"],
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
