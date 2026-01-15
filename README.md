# Coffee-Tag Machine

This readme mainly describes how to install and use this python package
[on the raspberry](#production-setup) and [how to develop it](#development-setup).

> [!important]
> It is possible to use other technics to install/dev/use this package (e.g. conda)
> but the officially supported ones are `pipx` in production and virtual environment in development.

[[_TOC_]]

## Usage

In production, the app can be launched with the `coffee_tag` cli. When in dev, you need to do `python -m coffee_tag`.

The nominal command is `coffee_tag COFFEE_PRICE PATH_TO_DB`.
Additional arguments and flags are described with the `-h` argument.

> [!note]
> In production, it is recommended to use an absolute path for the database to avoid any error.

## Production Setup

### Initial configuration of the Raspberry PI (do once)

#### Wiring

| Usage              | Pin | Left Signal     | Right Signal      | Pin | Usage           |
|--------------------|-----|-----------------|-------------------|-----|-----------------|
|                    | 1   | 3V3 Power       | 5V Power          | 2   | PN532 (red)     |
| PN532 SDA (yellow) | 3   | GPIO2 (SDA1)    | 5V Power          | 4   | SCREEN (red)    |
| PN532 SCL (green)  | 5   | GPIO3 (SCL1)    | GND               | 6   | SCREEN (brown)  |
|                    | 7   | GPIO4           | GPIO14 (TXD0)     | 8   | JURA RX (brown) |
| JURA (black)       | 9   | GND             | GPIO15 (RXD0)     | 10  | JURA TX (blue)  |
|                    | 11  | GPIO17          | GPIO18 (PWM0)     | 12  |                 |
|                    | 13  | GPIO27          | GND               | 14  | PN532 (brown)   |
|                    | 15  | GPIO22          | GPIO23            | 16  | JURA  (white)   |
|                    | 17  | 3V3 Power       | GPIO24            | 18  |                 |
|                    | 19  | GPIO10 (MOSI)   | GND               | 20  |                 |
|                    | 21  | GPIO9 (MISO)    | GPIO25            | 22  |                 |
|                    | 23  | GPIO11 (SCLK)   | GPIO8 (CE0)       | 24  |                 |
|                    | 25  | GND             | GPIO7 (CE1)       | 26  |                 |
|                    | 27  | GPIO0 (ID_SD)   | GPIO1 (ID_SC)     | 28  |                 |
|                    | 29  | GPIO5           | GND               | 30  |                 |
|                    | 31  | GPIO6           | GPIO12 (PWM0)     | 32  |                 |
|                    | 33  | GPIO13 (PWM1)   | GND               | 34  |                 |
|                    | 35  | GPIO19 (PCM_FS) | GPIO16            | 36  |                 |
|                    | 37  | GPIO26          | GPIO20 (PCM_DIN)  | 38  |                 |
|                    | 39  | GND             | GPIO21 (PCM_DOUT) | 40  |                 |

#### Software

When creating the image, select Raspberry PI 2 and choose the 32-bit desktop image.
Also edit `/boot/firmware/config.txt` and change the following lines:

```
dtparam=i2c_arm=off
dtparam=spi=off
```

Finally, to ensure the Raspberry PI 2 stays up to date (literally), add a cron task (with `sudo crontab -e`):

```cron
0 1 * * * date -s "$(wget --method=HEAD -qSO- --max-redirect=0 google.com 2>&1 | sed -n 's/^ *Date: *//p')"
```

> [!note]
> This is currently required as the IT blocks NTP requests.

To be able to download the app, add the relevant pypi index in `pip.conf`:

```ini
[global]
extra-index-url =
    https://www.piwheels.org/simple
    https://__token__:[token]@gitlab.ensta.fr/api/v4/groups/3178/-/packages/pypi/simple
```

> [!note]
> The token needs to be created [here](https://gitlab.ensta.fr/groups/u2is-coffee-team/-/settings/access_tokens)
> with read_api scope and developer role.

Install the dependencies with

```shell
apt install -y python3-tk python3-pillow libjpeg-dev
```

Then install [pipx](https://github.com/pypa/pipx) with the official tutorial.
Finally, install this app with `pipx install coffee-tag`.

That's it, the setup is ready to be used. See [Usage](#usage) to use it!

### Upgrade the app (for every new version)

First, close the app and make a copy of the database. Then `pipx upgrade coffee-tag` and
finally restart the app.

## Development Setup

To create a virtual environment, perform the following commands:

```bash
apt install python3-tk python3-pillow libjpeg-dev # install the linux dependencies
python3 -m venv .venv # create a virtual env 
source .venv/bin/activate # activate the virtual env (to do everytime)
pip install -r requirements.txt # install dependencies
```

While developing, be sure to use the argument `--dev` to prevent the app from trying to connect to the rfid reader.

At the time of writing (16/12/25), the recommended command to use is
`coffee_tag 0.25 coffee.db --no-authentication --dev --verbose --read-only`.

### Docs

- Test RFID reader
    - 13.56
      MHz [NTC reader](https://www.amazon.fr/Waveshare-PN532-NFC-Communication-Interfaces/dp/B07WHGFN6Z/ref=sr_1_2_sspa?__mk_fr_FR=%C3%85M%C3%85%C5%BD%C3%95%C3%91&crid=3DV8WZ0BFNH96&keywords=Waveshare%2BPN532%2BNFC&qid=1674221120&sprefix=waveshare%2Bpn532%2Bnfc%2Caps%2C71&sr=8-2-spons&sp_csd=d2lkZ2V0TmFtZT1zcF9hdGY&th=1)
    - Doc [here](https://www.raspberrypi.com/news/read-rfid-and-nfc-tokens-with-raspberry-pi-hackspace-37/)
      or [here](https://www.waveshare.com/wiki/PN532_NFC_HAT#Features)
    - 125 kHz [reader](https://www.gotronic.fr/art-lecteur-rfid-grove-125-khz-113020002-19038.html)

### Gitlab CI

The python package is automatically built when a branch is merged on main, a release
is created [here](https://gitlab.ensta.fr/u2is-coffee-team/coffee_tag/-/releases), and it is published
to the GitLab pypi index to be available for download.

The pipeline first builds the package with the build module, then with GitLab API and the twine module
publishes the release and the package.
Please refer to [.gitlab-ci.yml](.gitlab-ci.yml) for the exact details of the pipeline.

> [!note]
> The DSI (IT service) doesn't provide any runners on the GitLab. The
> [U2IS Runner](https://u2is.ovh/en/tech/tools/gitlab-runner) was added to the group.

> [!tip]
> To allow releases creation, create a
> token [here](https://gitlab.ensta.fr/u2is-coffee-team/coffee_tag/-/settings/access_tokens) with the permission
> `api`, `write_repository` with the role `Developer`, then create the variable
>
`RELEASE_TOKEN` [here](https://gitlab.ensta.fr/u2is-coffee-team/coffee_tag/-/settings/ci_cd#js-cicd-variables-settings).
