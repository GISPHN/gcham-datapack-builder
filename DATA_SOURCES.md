# Data sources and attribution

G-CHAM Data Pack Builder downloads source data at run time. No Census or N03 datasets are bundled in the plugin package.

## 2020 Population Census 250 m mesh statistics

Source service: Portal Site of Official Statistics of Japan (e-Stat), Statistics GIS.

The plugin uses six JGD2011 250 m mesh tables from the 2020 Population Census:

- Population and households (`T001142`)
- Population migration, labour-force status, place of work/school (`T001145`)
- Population by five-year age group (`T001196`)
- Population aged 15+ by labour-force status, industry and occupation (`T001197`)
- Housing ownership and type (`T001198`)
- Residence five years earlier and place of work/school (`T001199`)

Users are responsible for complying with the current e-Stat terms of use and for providing appropriate source attribution when publishing derived products. The plugin transforms and integrates the source data; derived outputs should not be represented as products created or endorsed by the Government of Japan.

Official terms: https://www.e-stat.go.jp/terms-of-use
Statistics GIS terms: https://www.e-stat.go.jp/gis-terms

Suggested attribution for a derived output:

> Source: 2020 Population Census, Portal Site of Official Statistics of Japan (e-Stat); processed with G-CHAM Data Pack Builder.

## Administrative boundaries (N03, 2026)

Source service: National Land Numerical Information download service, Ministry of Land, Infrastructure, Transport and Tourism (MLIT), Japan.

The plugin uses the 2026 Administrative Area (N03) dataset. The N03 download page identifies the dataset as CC BY 4.0 and states that it was prepared using source materials including Geospatial Information Authority of Japan (GSI) products and the national local-government code list. The same page notes that additional procedures with GSI may be required for some secondary uses.

Users should check the current N03 download page and applicable source-data conditions before redistribution or other secondary use.

Official N03 page: https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html

Suggested attribution for a derived output:

> Source: National Land Numerical Information, Administrative Area (N03), MLIT, Japan; processed with G-CHAM Data Pack Builder.

## Plugin license versus data licenses

The plugin source code is licensed under GPL-2.0-or-later. This software license does not replace or modify the terms governing data downloaded from e-Stat, MLIT, GSI, or other source providers.
