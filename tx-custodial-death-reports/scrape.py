import os
import time
import random
import glob
from datetime import datetime
from zoneinfo import ZoneInfo
import csv

import requests
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

html_dir = 'pages'
base_url = 'https://oag.my.site.com'


def download_pages():

    url = f'{base_url}/cdr/cdrreportdeaths'

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(url)

        page.locator('#displayAllCheckbox').check()

        total_count = page.locator(
            '#mycdrs_info'
        ).inner_text().split('of')[-1].split('entries')[0].replace(',', '').strip()  # noqa
        total_count = int(total_count)

        pagination_html = page.locator('#mycdrs_paginate').inner_html()
        soup = BeautifulSoup(pagination_html, 'html.parser')
        last_page = soup.find('span').find_all(
            'a',
            {'class': 'paginate_button'}
        )[-1].text.strip()

        last_page = int(last_page)

        for page_number in range(1, last_page+1):
            table_html = page.locator('#tableDiv').locator('#mycdrs').inner_html()  # noqa

            html_filepath = os.path.join(
                html_dir,
                f'tx-cdr-reports-page-{page_number}.html'
            )

            with open(html_filepath, 'w') as outfile:
                outfile.write(table_html)

            print(f'Downloaded {html_filepath}')

            next_button = page.locator('#mycdrs_next')

            is_disabled = 'disabled' in next_button.evaluate('node => node.className')  # noqa

            if is_disabled:
                break
            else:
                next_button.click()

            time.sleep(random.uniform(1, 2))

        browser.close()

    return total_count


def get_fips_lookup():
    lookup = {}

    r = requests.get(
        'https://www2.census.gov/geo/docs/reference/codes2020/cou/st48_tx_cou2020.txt'  # noqa
    )
    r.raise_for_status()

    lines = r.text.splitlines()
    
    for line in lines[1:]:
        _, statefips, countyfips, _, countyname, _, _ = line.split('|')
        county = countyname.replace('County', '').strip().upper()
        lookup[county] = f'{statefips}{countyfips}'

    # get it together, texas
    fuckups = {
        'Tom_Green': '48451',
        'Van_Zandt': '48467',
        'De Witt': '48123',
        'Live_Oak': '48297'
    }

    return {**lookup, **fuckups}


def scrape_data():

    fips_lookup = get_fips_lookup()

    def clean_text(txt):
        txt = ' '.join(txt.split())
        if txt == '-':
            txt = ''
        return txt

    data = []

    csv_filename = 'tx-custodial-deaths.csv'

    headers = [
        'county',
        'county_fips',
        'agency',
        'tdcj_unit',
        'cdr_number',
        'name',
        'report_pdf_link',
        'death_date',
        'death_datetime_utc',
        'report_datetime_utc',
        'version_type',
        'version_no'
    ]

    html_files = glob.glob(
        os.path.join(
            html_dir,
            '*.html'
        )
    )

    for file in html_files:
        with open(file, 'r') as infile:
            html = infile.read()

        table = BeautifulSoup(html, 'html.parser').find('tbody')
        rows = table.find_all('tr')

        for row in rows:
            (
                agency,
                county,
                tdcj_unit,
                cdr_number,
                name,
                death_datetime,
                report_datetime,
                version_type,
                version_no
            ) = row

            county = clean_text(county.text)

            fips = ''
            if fips_lookup.get(county.upper()):
                fips = fips_lookup.get(county.upper())

            is_mountain_tz = county.upper() in ['EL PASO', 'HUDSPETH']

            tz_central = ZoneInfo('US/Central')
            tz_mountain = ZoneInfo('US/Mountain')
            tz_utc = ZoneInfo('UTC')

            try:
                death_datetime = datetime.strptime(
                    clean_text(death_datetime.text),
                    '%m/%d/%Y %H:%M %p'
                )

                death_date = death_datetime.date().isoformat()

                if is_mountain_tz:
                    death_datetime = death_datetime.replace(
                        tzinfo=tz_mountain
                    )
                else:
                    death_datetime = death_datetime.replace(
                        tzinfo=tz_central
                    )

                death_datetime = death_datetime.astimezone(
                    tz_utc
                ).isoformat(timespec='minutes').replace(
                    '+00:00', ''
                )
            except ValueError:
                death_datetime = clean_text(death_datetime.text)
                death_date = ''

            try:
                report_datetime = datetime.strptime(
                    clean_text(report_datetime.text),
                    '%m/%d/%Y %H:%M %p'
                )

                if is_mountain_tz:
                    report_datetime = report_datetime.replace(
                        tzinfo=tz_mountain
                    )
                else:
                    report_datetime = report_datetime.replace(
                        tzinfo=tz_central
                    )

                report_datetime = report_datetime.astimezone(
                    tz_utc
                ).isoformat(timespec='minutes').replace(
                    '+00:00', ''
                )
            except ValueError:
                report_datetime = clean_text(report_datetime.text)

            pdf_link = name.find('a')

            if pdf_link:
                report_pdf_link = f'{base_url}{pdf_link.get("href")}'
            else:
                report_pdf_link = ''

            data.append({
                'agency': clean_text(agency.text),
                'county': county,
                'county_fips': fips,
                'tdcj_unit': clean_text(tdcj_unit.text),
                'cdr_number': clean_text(cdr_number.text),
                'name': clean_text(name.text),
                'death_date': death_date,
                'death_datetime_utc': death_datetime,
                'report_datetime_utc': report_datetime,
                'version_type': clean_text(version_type.text),
                'version_no': clean_text(version_no.text),
                'report_pdf_link': report_pdf_link
            })

    data.sort(
        key=lambda x: (
            x.get('death_datetime_utc'),
            x.get('name')
        )
    )

    with open(csv_filename, 'w') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data)

    print(f'Wrote file: {csv_filename}')


if __name__ == '__main__':
    download_pages()
    scrape_data()
