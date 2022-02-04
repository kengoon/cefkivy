#!/usr/bin/env python
# -*- coding: UTF-8 -*-

#===============================================================================
# Written by Rentouch 2013 - http://www.rentouch.ch
#===============================================================================

from setuptools import setup

install_reqs = ['argparse', 'cefpython3']

# -----------------------------------------------------------------------------
import cefkivy

# setup
setup(name='cefkivy',
      version=cefkivy.__version__,
      author='Rentouch GmbH',
      author_email='info@rentouch.ch',
      url='http://www.rentouch.ch',

      package_data={'cefkivy': ['images/*.png', '*.kv']},

      packages=['cefkivy', ],

      install_requires=install_reqs
)

# -----------------------------------------------------------------------------

