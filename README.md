# G-CHAM Data Pack Builder

G-CHAM Data Pack Builder is a QGIS plugin for creating municipality-level data packs for **GIS-based Community Health Assessment Methods (G-CHAM)** from official Japanese open data.

The plugin automates the workflow from source download to ready-to-use FlatGeobuf layers. Its primary target is QGIS 4.x, with compatibility code retained for QGIS 3.44 LTR where practical.

> This is an independently developed third-party QGIS plugin. It is not an official product of QGIS.org, the Statistics Bureau of Japan, e-Stat, the Ministry of Land, Infrastructure, Transport and Tourism (MLIT), or the Geospatial Information Authority of Japan (GSI).

## Main features

- Select any prefecture in Japan.
- Download six 2020 Population Census 250 m JGD2011 mesh-statistics tables from e-Stat.
- Download the 2026 National Land Numerical Information N03 administrative-boundary dataset for the selected prefecture.
- Join the six Census tables by `KEY_CODE`.
- Keep the G-CHAM preset of 128 source attributes and optionally add any other available Census fields.
- Use the first header row for `KEY_CODE`, `HTKSYORI`, `HTKSAKI`, and `GASSAN`, and the second Japanese header row for statistical field names.
- Validate and process suppressed/aggregated meshes using `HTKSYORI`, `HTKSAKI`, and `GASSAN`.
- Calculate the percentage of population aged 0–14, 15–64, and 65+ after suppression merging, using total population as the denominator.
- Round derived percentages to one decimal place using conventional half-up rounding.
- Dissolve N03 administrative boundaries by `N03_007`.
- Use `N03_005` as the displayed municipality name when present; otherwise use `N03_004`.
- Assign each intact 250 m mesh to exactly one municipality using the mesh center point.
- Create all municipalities in a prefecture or only user-selected municipalities.
- Export FlatGeobuf (`.fgb`) with ASCII-only physical file names and Japanese QGIS layer names.
- Preserve a prefecture-wide 250 m population layer in addition to municipality-level outputs.
- Output in the JGD2011 Japan Plane Rectangular Coordinate System selected for the prefecture.
- Automatically add outputs to the QGIS layer tree in the `行政区域` and `250mメッシュ人口` groups.
- Reuse previously downloaded e-Stat/N03 archives from the local cache.

## Output examples

For Nara Prefecture and Nara City:

```text
<user-selected-folder>/
├─ admin/
│  ├─ n03_29201_admin.fgb
│  └─ ...
├─ population/
│  ├─ census2020_29_pop250m.fgb
│  ├─ census2020_29201_pop250m.fgb
│  └─ ...
└─ _cache/
   ├─ estat/
   └─ n03/
```

QGIS layer names are displayed in Japanese, for example:

- `奈良市_行政区域_国土数値情報`
- `奈良県_250mメッシュ人口_2020国調`
- `奈良市_250mメッシュ人口_2020国調`

## Default styling

### Administrative boundaries

- transparent fill
- orange outline
- outline width: 0.96 mm
- layer opacity: 70%
- municipality-name labels
- white label buffer: 1.0 mm
- label-buffer opacity: 80%

### 250 m population mesh

- classification field: `人口（総数）`
- classification recalculated independently for each municipality layer
- Jenks natural breaks
- 10 classes
- blue → white → red color ramp
- layer opacity: 70%

## Suppressed meshes

The plugin respects the e-Stat suppression/aggregation fields.

- `HTKSYORI = 0`: ordinary mesh
- `HTKSYORI = 1`: aggregation destination
- `HTKSYORI = 2`: suppressed source mesh

Suppressed source meshes are not emitted as independent features. Their applicable values and geometry are associated with the aggregation destination according to the source fields. Derived age-group percentages are calculated only after this processing so that numerator, denominator, and output geometry refer to the same aggregation area.

Before processing, the plugin also checks the suppression/aggregation metadata across the six source tables. If the relevant metadata are inconsistent, processing stops rather than silently producing potentially incorrect integrated data.

## Municipality allocation

The 250 m mesh geometry is not clipped by municipal boundaries.

For each mesh, the plugin calculates the center point from the 10-digit `KEY_CODE` and assigns the full mesh to the municipality containing that point. This prevents one mesh from being duplicated across neighboring municipality outputs and preserves the original mesh geometry.

For the rare case in which the center point lies exactly on a boundary, the plugin uses the municipality with the largest overlap with the intact mesh. A deterministic municipality-code rule is used if a tie remains.

For a suppressed aggregation feature containing multiple mesh parts, the aggregation destination `KEY_CODE` is used as the representative municipality assignment.

## Coordinate reference systems

Outputs use JGD2011 Japan Plane Rectangular Coordinate System coordinates. For example, Nara Prefecture uses Zone VI (`EPSG:6674`).

Some prefectures, particularly Hokkaido, Tokyo, Kagoshima, and Okinawa, span multiple official plane-rectangular zones. Version 1.0.1 uses a prefecture-level principal zone for the combined prefecture workflow and records a warning in the execution log for these prefectures. Users working with remote islands or precision-sensitive projected measurements should verify the appropriate local zone for their intended analysis.

## Installation

### Official QGIS Plugin Repository

After the plugin has been approved in the official QGIS repository:

1. Open QGIS.
2. Choose **Plugins → Manage and Install Plugins**.
3. Search for `G-CHAM Data Pack Builder`.
4. Click **Install Plugin**.

### Install from ZIP

For development or pre-release testing:

1. Open QGIS.
2. Choose **Plugins → Manage and Install Plugins**.
3. Open **Install from ZIP**.
4. Select the release ZIP.
5. Start `G-CHAM Data Pack Builder` from the toolbar or Plugins menu.

## Basic workflow

1. Select a prefecture.
2. Choose either all municipalities or selected municipalities.
3. Keep `G-CHAMデータパック用データ` enabled, and optionally select additional Census fields.
4. Choose the output folder.
5. Run `データパックを作成`.
6. Review progress and logs in the plugin dialog.

The first run downloads source archives. Subsequent runs can reuse files stored under `_cache` in the selected output directory.

## Data sources and licenses

The plugin source code is licensed under **GPL-2.0-or-later**.

The plugin does not bundle Census or N03 source datasets. They are downloaded from their official providers at run time and remain subject to the providers' respective terms and source-attribution requirements.

See [DATA_SOURCES.md](DATA_SOURCES.md) for source details, attribution guidance, and links to the current official terms.

## Privacy and network access

The plugin does not require an e-Stat API key, user account, or personal information. It accesses public government download endpoints using QGIS networking facilities. Output and cached source archives are written under the folder selected by the user.

## Issues and feature requests

Please use the GitHub issue tracker:

https://github.com/GISPHN/gcham-datapack-builder/issues

When reporting a bug, include the QGIS version, operating system, prefecture/municipality selection, reproduction steps, and relevant plugin log lines. Do not include confidential or personal data.

## Citation

If you use this plugin in research, please cite the software and the underlying source datasets. A machine-readable citation file is provided as [CITATION.cff](CITATION.cff).

## Author

GISPHN (Ryo Horiike)  
ryo.horiike@naramed-u.ac.jp

---

# 日本語

G-CHAM Data Pack Builder は、**GIS-based Community Health Assessment Methods（G-CHAM）** のデータパック作成を自動化するQGISプラグインです。

都道府県を選択するだけで、e-Statの令和2年国勢調査250mメッシュ統計6表と、国土数値情報の行政区域N03を取得し、必要項目の抽出、`KEY_CODE` 結合、秘匿地域処理、割合計算、自治体への250mメッシュ割当、FlatGeobuf出力、QGISへのレイヤ追加までを一括処理します。

## 主な処理

- 任意の都道府県を選択
- 令和2年国勢調査250mメッシュ・JGD2011の6表をe-Statから自動取得
- 国土数値情報 N03 2026行政区域を自動取得
- `KEY_CODE` で6表を結合
- G-CHAMデータパック用の128項目をプリセットとして保持
- 必要に応じて他の統計項目を追加選択
- `KEY_CODE`, `HTKSYORI`, `HTKSAKI`, `GASSAN` は1行目の列名を使用し、それ以外は2行目の日本語項目名を採用
- `HTKSYORI / HTKSAKI / GASSAN` に基づいて秘匿地域・合算地域を処理
- 0～14歳、15～64歳、65歳以上人口割合を秘匿処理後に計算
- 割合は小数第2位を四捨五入して小数第1位まで保存
- `N03_007` で行政区域を融合
- `N03_005` が存在すれば行政区名、なければ `N03_004` を自治体名として使用
- 250mメッシュの中心点が含まれる自治体へ当該メッシュを一意に割当
- 全自治体または選択自治体のみを出力
- 都道府県全体の250m人口FGBも保存
- FGBの物理ファイル名は英数字・アンダースコアを基本とし、QGISレイヤ名は日本語
- 選択都道府県に対応するJGD2011平面直角座標系で出力
- `行政区域` と `250mメッシュ人口` の2つのレイヤグループへ自動追加
- 自治体は `N03_007` の昇順で表示
- ダウンロード済みデータを `_cache` から再利用可能

## 注意事項

行政区域で250mメッシュをクリップしません。メッシュ中心点によって所属自治体を一意に決定し、元の250mメッシュ形状を保持します。

北海道、東京都、鹿児島県、沖縄県など、複数の平面直角座標系にまたがる都道府県については、v1.0.1では都道府県全体の処理に主要区域の系を使用し、実行ログに注意を表示します。離島等を含む高精度な距離・面積解析を行う場合は、目的地域に適した系を確認してください。

データの利用・再配布にあたっては、e-Stat、国土数値情報、国土地理院等の最新の利用条件を確認してください。詳細は [DATA_SOURCES.md](DATA_SOURCES.md) に整理しています。
