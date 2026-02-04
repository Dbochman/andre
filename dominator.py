#!/usr/bin/env python
import pyen

def main():
    en = pyen.Pyen('2NVCPOTJ34PVWCTLN')
    cats = en.get('catalog/list', results=100)['catalogs']
    rv = []
    for cat in cats:
        contents = en.get('catalog/read', results=1000, id = cat['id'])
        count = sum(x['play_count'] for x in  contents['catalog']['items'] if 'play_count' in x)
        print(cat['name'], cat['total'], count)

if __name__ == '__main__':
    main()
