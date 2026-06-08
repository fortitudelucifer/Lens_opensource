# Quick Start

## 1. Clone and enter the repository

```bash
git clone <repo-url>
```

## 2. Create the Python environment

```bash
conda env create -f environment.yml
conda activate wechatDHA
```

## 3. Install frontend dependencies

```bash
npm install --prefix frontend
```

## 4. Prepare local configuration

```bash
cp local_secrets/.env.advisor.example local_secrets/.env.advisor
cp configs/anonymization.yaml.template configs/anonymization.yaml
cp configs/confirmed_names.yaml.template configs/confirmed_names.yaml
```

Fill local secrets and private name mappings locally. Do not commit real keys, names, chat logs, model weights, or generated runtime data.

## 5. Start backend and frontend

```bash
conda run -n wechatDHA python scripts/advisor/api/server.py
npm run dev --prefix frontend
```
