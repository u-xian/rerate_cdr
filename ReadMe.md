This is python program that generate fake CDRs and rerate them to find out incorrect tariff that may affect customers or compamny revenues.

This rerate_cdr has two json files : cdr_config.json that holds configurations to generate the fake CDRs and Call_Tariff for tariff of local and international destinations.

It has also two python programs : gen_cdr.py to generate CDRs and rate_cdr to rerate the generated CDRs.

How to use it

### 1. Clone the repo

```
clone https://github.com/u-xian/rerate_cdr.git
```

### 2. Enter into directory

```
cd rerate_cdr
```

### 3. Create Python environment

```
python3 -m venv .venv
```

### 4. Activate environment

```
source .venv/bin/activate
```

### 5. Install dependencies

```
pip install -r requirements.txt
```

### 6. Generate the fake CDRS and a csv file named cdrs.csv will be generated

```
python gen_cdr.py 2000
```

### 7. Rerate the generated CDRs and a csv file named cdrs_rated will be generated

```
python rate_cdr.py
```
