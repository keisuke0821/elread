#!/bin/sh

if [ `/bin/ps aux |/bin/grep gb |/bin/grep "/elread/elread.py" |/bin/grep -v grep |/usr/bin/wc -l\
` = 0 ];
then
    /bin/rm /tmp/el_enc.lock;
else
    /bin/echo "elread.py running";
fi
