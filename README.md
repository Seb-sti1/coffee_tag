# Coffee-Tag Machine

This readme mainly describes how to install and use this python package
[on the raspberry](#production-setup) and [how to develop it](#development-setup).

## Production Setup

### Build this python package

To build the package, run the commands below

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install build
```

The package is then available in `dist/coffee_tag-*-py3-none-any.whl`

### Install python package

Install linux dependencies `apt install python3-tk`. Then use the built package
`coffee_tag.whl`, and install it using `pip install ./coffee_tag.whl`, or
with [pipx](https://github.com/pypa/pipx) using `pipx install ./coffee_tag.whl`.

### Launch Application

If you have installed the package using pip, use `python3 -m coffee_tag`. If you used pipx, you can directly run
`coffee_tag`.

#### Alternative method (without python package)

If you don't want to build and install the python pacakge, you can install all the dependencies using pip:

```bash
python3 -m venv .venv # create a virtual env 
source .venv/bin/activate # activate the virtual env (to do everytime)
pip install -r requirements.txt # install dependencies
```

And then launch the app from the root folder:

```bash
python3 -m coffee_tag
```

## Development Setup

We encourage the use of environments, you can perform the following commands:

```bash
apt install python3-tk # install the linux dependencies
python3 -m venv .venv # create a virtual env 
source .venv/bin/activate # activate the virtual env (to do everytime)
pip install -r requirements.txt # install dependencies
```

> [!important]
> Be sure to set the `DEV_MODE` variable to `True` in [coffee.py](coffee_tag/coffee.py)

> [!tip]
> If you have conda installed
> ```bash
> conda create -n coffee && conda activate coffee
> conda install pip
> pip install -r requirements.txt
> ```

## Docs

- Test RFID reader
    - 13.56
      MHz [NTC reader](https://www.amazon.fr/Waveshare-PN532-NFC-Communication-Interfaces/dp/B07WHGFN6Z/ref=sr_1_2_sspa?__mk_fr_FR=%C3%85M%C3%85%C5%BD%C3%95%C3%91&crid=3DV8WZ0BFNH96&keywords=Waveshare%2BPN532%2BNFC&qid=1674221120&sprefix=waveshare%2Bpn532%2Bnfc%2Caps%2C71&sr=8-2-spons&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY&th=1)
    - Doc [here](https://www.raspberrypi.com/news/read-rfid-and-nfc-tokens-with-raspberry-pi-hackspace-37/)
      or [here](https://www.waveshare.com/wiki/PN532_NFC_HAT#Features)
    - 125 kHz [reader](https://www.gotronic.fr/art-lecteur-rfid-grove-125-khz-113020002-19038.html)
