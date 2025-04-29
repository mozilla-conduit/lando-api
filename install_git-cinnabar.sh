#!/usr/bin/env bash

curl https://raw.githubusercontent.com/glandium/git-cinnabar/master/download.py -o download.py
chmod u+x download.py
./download.py --exact 0.7.2
chmod a+x git-cinnabar
chmod a+x git-remote-hg
