# Coffee-Tag Machine

This readme mainly describes how to install and use this python package
[on the raspberry](#production-setup) and [how to develop it](#development-setup).

## Production Setup

### Initial configuration of the Raspberry PI

When creating the image, select Raspberry PI 2 and choose the 32-bit desktop image.
Also edit `/boot/firmware/config.txt` and change the following lines:
```
dtparam=i2c_arm=off
dtparam=spi=off
```

Finally, to ensure the Raspberry PI 2 stays up to date (literally), add a cron task (with `crontab -e`):
```cron
0 1 * * * sudo date -s "$(wget --method=HEAD -qSO- --max-redirect=0 google.com 2>&1 | sed -n 's/^ *Date: *//p')"
```


### Build this python package

> [!tip]
> The python package it automatically built when a branch is merged on main.
> See all releases [here](https://gitlab.ensta.fr/u2is-coffee-team/coffee_tag/-/releases).
> See how to configure the CI [here](#gitlab-ci).

To build the package, run the commands below

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install build
```

The package is then available in `dist/coffee_tag-*-py3-none-any.whl`

### Install python package

Install linux dependencies `apt install python3-tk python3-pillow libjpeg-dev`. Then use the built package
`coffee_tag.whl`, and install it using `pip install ./coffee_tag.whl`, or
with [pipx](https://github.com/pypa/pipx) using `pipx install ./coffee_tag.whl`.

> [!tip]
> If this steps take lot of time, chances are there is dependency that is rebuilding on the Raspberry PI.
> One way to find which one is to do `pip wheel -r requirements.txt` and find which dependencies are just download
> and those that need to be recompiled.

### Launch Application

If you have installed the package using pip, use `python3 -m coffee_tag`. If you used pipx, you can directly run
`coffee_tag`.

### Alternative method (without python package) (not recommended)

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
apt install python3-tk python3-pillow libjpeg-dev # install the linux dependencies
python3 -m venv .venv # create a virtual env 
source .venv/bin/activate # activate the virtual env (to do everytime)
pip install -r requirements.txt # install dependencies
```

> [!important]
> Be sure to use the argument ` --dev ` variable to `True` in [coffee.py](coffee_tag/coffee.py)

> [!tip]
> If you have conda installed
> ```bash
> conda create -n coffee && conda activate coffee
> conda install pip
> pip install -r requirements.txt
> ```

## Gitlab CI

### Gitlab Runner

The DSI (IT service) doesn't provide any runners on the GitLab. I (Sébastien Kerbourc'h) added DaTA's one (computer
science club).

### Automated release configuration

Create a token [here](https://gitlab.ensta.fr/u2is-coffee-team/coffee_tag/-/settings/access_tokens) with the permission
`api`, `write_repository` with the role `Developer`, then create the variable
`RELEASE_TOKEN` [here](https://gitlab.ensta.fr/u2is-coffee-team/coffee_tag/-/settings/ci_cd#js-cicd-variables-settings).

## Docs

- Test RFID reader
    - 13.56
      MHz [NTC reader](https://www.amazon.fr/Waveshare-PN532-NFC-Communication-Interfaces/dp/B07WHGFN6Z/ref=sr_1_2_sspa?__mk_fr_FR=%C3%85M%C3%85%C5%BD%C3%95%C3%91&crid=3DV8WZ0BFNH96&keywords=Waveshare%2BPN532%2BNFC&qid=1674221120&sprefix=waveshare%2Bpn532%2Bnfc%2Caps%2C71&sr=8-2-spons&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY&th=1)
    - Doc [here](https://www.raspberrypi.com/news/read-rfid-and-nfc-tokens-with-raspberry-pi-hackspace-37/)
      or [here](https://www.waveshare.com/wiki/PN532_NFC_HAT#Features)
    - 125 kHz [reader](https://www.gotronic.fr/art-lecteur-rfid-grove-125-khz-113020002-19038.html)
