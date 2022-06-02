from time import sleep
import psycopg2
import os
import json
from log import logging
from request import req
from discord_webhook import DiscordWebhook, DiscordEmbed
from datetime import datetime, timezone


if __name__ != "__main__":
    raise Exception('Run genshin.py as main')

logging.info('Genshin Auto Redeem Code Starting ...')

cookie = os.environ.get('COOKIE', '')
logging.info('Reading Genshin cookie from environment variable ..')

if (cookie == ''):
    logging.error("Variable 'COOKIE' not found, please ensure that variable exists")
    exit(1)
else: 
    logging.info("Variable 'COOKIE' found")

cookies = cookie.split('#')

pg_dsn = os.environ.get('DATABASE_URL')

if (pg_dsn == ''):
    logging.error("Variable 'DATABASE_URL' not found, please ensure that variable exists")
    exit(1)
else: 
    logging.info("Variable 'DATABASE_URL' found")

try:
    logging.info('Connecting to Database ...')
    conn = psycopg2.connect(pg_dsn)
except psycopg2.Error as e:
    logging.error('Connection Error: {}'.format(e))
    exit(1)

cursor = conn.cursor()

# Checking table
cursor.execute("SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename  = 'redeemed_code');")
row = cursor.fetchone()

# Creating table
if row[0] == False:
    logging.info('Table redeemed_code not exist, creating ..')
    cursor.execute("CREATE TABLE redeemed_code (id SERIAL PRIMARY KEY, uid varchar(30), code varchar(30), redeemed_at timestamp, CONSTRAINT UC_Code UNIQUE (uid,code))")
    conn.commit()

codes = req.to_python(req.request(
    'get',
    'https://raw.githubusercontent.com/ataraxyaffliction/gipn-json/main/gipn.json'
).text).get('CODES', {})

available_codes = []

for code in codes:
    if (code.get('is_expired', True) == False):
        available_codes.append(code)

if (len(cookies) > 1):
    logging.info(f'Multiple account detected, number of account {len(cookies)}')

fail = 0
for no in range(len(cookies)):
    logging.info(f'Verifiying cookies number: {no+1}')
    header = {
        'User-Agent': os.environ.get(
            'USER_AGENT', 
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36 Edg/101.0.1210.47'
        ),
        'Referer': 'https://act.hoyolab.com',
        'Accept-Encoding': 'gzip, deflate, br',
        'Cookie': cookies[no]
    }

    res = req.to_python(req.request(
        'get',
        'https://api-account-os.hoyolab.com/auth/api/getUserAccountInfoByLToken',
        headers=header
    ).text)

    if (res.get('retcode', 0) != 0):
        logging.error("Variable 'COOKIE' not valid, please ensure that value is valid")
        fail +=1
        continue
    else:
        logging.info('Account cookie is valid')

    logging.info('Scanning for genshin account')
    index = 0
    res = req.to_python(req.request(
        'get',
        'https://api-os-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie?game_biz=hk4e_global',
        headers=header
    ).text)

    account_list = res.get('data', {}).get('list', [])

    if len(account_list) != 1:
        highest_level = account_list[0].get('level', 'NA')

    for i in range(1, len(account_list)):
        if account_list[i].get('level', 'NA') > highest_level:
            highest_level = account_list[i].get('level', 'NA')
            index = i

    region_name = account_list[index].get('region_name')
    uid = account_list[index].get('game_uid')
    level = account_list[index].get('level')
    nickname = account_list[index].get('nickname', '')
    region = account_list[index].get('region', '')

    logging.info('Genshin Impact Account found in server {}'.format(region_name))

    logging.info('Fetch account detail from hoyoverse ...')
    res = req.to_python(
        req.request('get', 'https://hk4e-api-os.mihoyo.com/event/sol/info?act_id=e202102251931481', headers=header).text
    )

    cursor.execute("SELECT code FROM redeemed_code WHERE uid = %s", (uid,))
    codes = cursor.fetchall()

    redeemed_codes = []

    for code in codes:
        redeemed_codes.append(code[0])

    valid_codes = []

    for row in available_codes:
        if (row.get('code', '') not in redeemed_codes):
            valid_codes.append(row)

    if (len(valid_codes) <= 0):
        logging.info('No new redeem code')

    for row in valid_codes:
        code = row.get('code', '')
        rewards = row.get('reward', '')
        logging.info(f'Redeem code {code} by uid {uid}')

        res = req.to_python(req.request(
            'get',
            f'https://sg-hk4e-api.hoyoverse.com/common/apicdkey/api/webExchangeCdkey?uid={uid}&region={region}&lang=en&cdkey={code}&game_biz=hk4e_global',
            headers=header
        ).text)

        sleep(5)

        try:
            dt = datetime.now(timezone.utc)
            cursor.execute("INSERT INTO redeemed_code (uid, code, redeemed_at) VALUES (%s, %s, %s)", (uid, code, dt,))
        except psycopg2.Error as e:
            pass
        finally:
            conn.commit()
        
        if (res.get('retcode', -1) != 0):
            logging.error(f'Code \'{code}\' has been claimed')
            fail +=1
            continue
    
        webhook = os.environ.get('DISCORD_WEBHOOK','')
        if (webhook != ''):
            webhook = DiscordWebhook(url=webhook)
            embed = DiscordEmbed(title='New Redeem Code has been redeemed', color='E6E18F')
            embed.set_author(
                name='Paimon',
                url='https://genshin.hoyoverse.com',
                icon_url='https://img-os-static.hoyolab.com/communityWeb/upload/1d7dd8f33c5ccdfdeac86e1e86ddd652.png',
            )
            embed.set_footer(text=f'Genshin Auto Login ({no+1}/{len(cookies)} Executed)', icon_url='https://img-os-static.hoyolab.com/communityWeb/upload/1d7dd8f33c5ccdfdeac86e1e86ddd652.png')
            embed.set_timestamp()
            embed.add_embed_field(name="Nickname", value=nickname)
            embed.add_embed_field(name="UID", value=uid)
            embed.add_embed_field(name="Code", value=code)
            embed.add_embed_field(name="Reward", value=rewards, inline=False)
            webhook.add_embed(embed)
            response = webhook.execute()
            if (response.status_code == 200):
                logging.info(f'Successfully send notification to your own discord')
            else:
                logging.error(f'Discord FAILED\n{response}')
        
conn.close()
if fail > 0:
    logging.error(f'{fail} redeemed code found')
logging.info('Script Ended')
exit(0)
