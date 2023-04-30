# Oracle Cloud Free Tier Provisioner

This script will help you to provision Oracle Cloud Infrastructure VM, 
especially for the free tier A1 Flex and E2 micro which is often out of capacity.

## Requirements

Python 3

## Setup

1. Create an API Signing Key. Follow [this tutorial](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm#two) for more info.

2. Setup Python virtual environment and install dependencies.
```bash
virtualenv env
source env/bin/activate
pip install -r requirements.txt
```

3. Edit some settings in `.env`.

4. Run the script and follow the prompts if required.
```bash
python main.py
```

 
> Good luck!