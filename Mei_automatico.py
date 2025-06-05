import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import datetime as dt
from time import sleep
import calendar

# Pacotes necessários para o driver
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By 
from selenium.webdriver.support.ui import WebDriverWait 
from selenium.webdriver.support import expected_conditions as EC 
from selenium.webdriver.chrome.options import Options 
from selenium.common.exceptions import TimeoutException 
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains

# As informações são mensais, realizamos a consulta somente no ultimo dia do mes
# criamos um dicionario, onde as chaves são o numero do mes e os valores a quanidade de dias que ele tem
# Usamos o calendar para detectar se o ano é bissexto ou nao
if calendar.isleap(today.year):
    last_day_month = {1:31,2:29,3:31,4:30,5:31,6:30,
           7:31,8:31,9:30,10:31,11:30,12:31}
else:
    last_day_month = {1:31,2:28,3:31,4:30,5:31,6:30,
           7:31,8:31,9:30,10:31,11:30,12:31}

# Buscamos a data de hoje
today = dt.datetime.now()

# Se hoje for o ultimo dia do mes, buscamos esse valor na consulta
if today.day == last_day_month[today.month]:
    last_update = today.strftime("%d%m%Y")
# Se não for, utilizamos a data do ultimo dia do mês anterior
else:
    if today.month != 1:
        last_update = dt.datetime(today.year, today.month - 1, last_day_month[today.month - 1]).strftime("%d%m%Y")
    # Se o mes for janeiro, utilizamos 31 de dezembro do ano anterior
    else:
        last_update = dt.datetime(today.year - 1, 12, 31).strftime("%d%m%Y")

# Geralmente, pedem os dados de forma anual para o acompanhamento 
# como o governo só tem quatro anos, vou inserir esses dados de forma manual
# por enquanto

fim2022 = '31122022'
fim2023 = '31122023'
fim2024 = '31122024'
date_generated = [fim2022, fim2023, fim2024, last_update]
date_generated

# criamos um dicionario vazio, que vamos atualizar no loop
MEIS = {}

# o autoinstaller checa se tem uma versão atualizada, se não tiver
# ele a atualiza e retorna o path do chromedriver
chrome_driver_path = chromedriver_autoinstaller.install()

for data in date_generated:
    # Inicializa o webdriver com o path do autoinstaller
    service = Service(executable_path = chrome_driver_path )
    driver = webdriver.Chrome(service=service)
    
    # Acessa a página inicial da receita federal com estatísticas de MEI
    driver.get('http://www22.receita.fazenda.gov.br/inscricaomei/private/pages/relatorios/opcoesRelatorio.jsf')
    # Clica na estatísitcas para UFs
    driver.find_element(By.XPATH, '//*[@id="1b"]/ul/li[3]/a').click()
    
    # Na caixa de texto no inicio da página, escreve a data
    text_input = driver.find_element(By.XPATH, '//*[@id="form:dataPesquisaInputDate"]')
    ActionChains(driver)\
        .send_keys_to_element(text_input, data).perform()
    
    # Essa linha acima gerava um bug que não entendia o motivo, esse webdriver wait
    # resolveu esse bug
    wait = WebDriverWait(driver, 3)
    
    # Aerta o botão de consulta 
    text_input = driver.find_element(By.XPATH, '//*[@id="form:botaoConsultar"]').click()
    
    # TO DO: tem um treco de esperar o elemento aparecer no webdriver
    # pois as vezes ele não consegue salvar os valores antes de passar pro próximo
    
    # Pega a fonte da página e sava os valores da tabela em uma lista chamada meis
    html = driver.page_source
    soup = BeautifulSoup(html, 'lxml')
    meis = soup.find_all("td", attrs = {'class': 'rich-table-cell'})
    
    # Fazemos dois loops, um para pegar o nome dos estados e o seu respectivo numero de meis
    # o loop é feito sobre a lista de meis acima
    
    # 'e' são as siglas dos estados, eles estão nos valores pares da lista meis
    e = [meis[p].text for p in range(0, len(meis)) if p%2 == 0]
    # 'm' são so meis de cada estado, eles estão nos valores impares da lista meis
    # o texto apreenta o separador de milhas, removemos ele para trasnformar o dataframe final em inteiro
    m = [meis[p].text.replace('.','') for p in range(0, len(meis)) if p%2 != 0]
    
    # Criamos um dicionario temporario, onde as chaves são os estados e os valores o
    # número de meis
    M = {e[j]:m[j] for j in range(0, len(e))}
    
    # Atualiza o dicionario MEIS com a data da consulta sendo a chave
    # e o valor o dicionario M criado
    try:
        MEIS.update({data: M})
    except IndexError:
        pass
    
    driver.quit()

# Salva o dicionario em dataframe, e transforma seus valores para o tipo inteiro
df = pd.DataFrame.from_dict(MEIS, orient='index')
df = df.astype('int')
df

# Cria o dataframe com os indices sendo os anos e os valores com o total de meis
# criados no ano
acumulado_pi = {
    2023: (df.loc[date_generated[1]]['PI'] - df.loc[date_generated[0]]['PI']),
    2024: (df.loc[date_generated[2]]['PI'] - df.loc[date_generated[1]]['PI']),
    2025: (df.loc[date_generated[3]]['PI'] - df.loc[date_generated[2]]['PI'])
}

# formata em dataframe
final_df = pd.DataFrame.from_dict(acumulado_pi , orient='index', columns = ['Total Meis'])
final_df 

# salva
final_df.to_csv('MEI_estoque_gov.csv',mode='w')