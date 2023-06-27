# Coffee-Tag Machine

## Launch Application

Install all the depencies using Pip:
```bash
pip install -r requirements.txt
```

To lauch the app from the root folder:
```bash
python3 source/python/coffee.py
```

## Developpement

We encourage the use of environments. If you have conda installed, you can perform the following commands:
```bash
conda create -n coffee && conda activate coffee
conda install pip
pip install -r dev_requirements.txt
```

If you don't use conda environments, just install depencies using the last command (`dev_requirements.txt`)

Be sure to set the `DEV_MODE` variable to `True` in [coffee.py](source/python/coffee.py)

## TODO and docs

- Test RFID reader
  - 13.56 MHz [NTC reader](https://www.amazon.fr/Waveshare-PN532-NFC-Communication-Interfaces/dp/B07WHGFN6Z/ref=sr_1_2_sspa?__mk_fr_FR=%C3%85M%C3%85%C5%BD%C3%95%C3%91&crid=3DV8WZ0BFNH96&keywords=Waveshare%2BPN532%2BNFC&qid=1674221120&sprefix=waveshare%2Bpn532%2Bnfc%2Caps%2C71&sr=8-2-spons&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY&th=1)
  - Doc [here](https://www.raspberrypi.com/news/read-rfid-and-nfc-tokens-with-raspberry-pi-hackspace-37/) or [here](https://www.waveshare.com/wiki/PN532_NFC_HAT#Features)

  - 125 kHz [reader](https://www.gotronic.fr/art-lecteur-rfid-grove-125-khz-113020002-19038.html)