**INSTALLATION**

*PN532 NFC HAT*
Install NFC lib using the documentation docs/nfc_tool_install.pdf
You can check the lib is well installed with
$ python3 source/python/example_get_uid.py 
(be sure to uncomment the chosen communication with the card : UART, I2C, SPI)

*App*
Install pillow and pandas for the GUI. Pip must already be installed
$ python3 -m pip install --upgrade Pillow
$ sudo apt-get install python3-pandas