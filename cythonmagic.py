# -*- coding: utf-8 -*-
"""
Cython related magics.

Author:
* Brian Granger

Parts of this code were taken from Cython.inline.
"""
#-----------------------------------------------------------------------------
# Copyright (C) 2010-2011, IPython Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

from __future__ import print_function

import imp
import io
import os
import sys

try:
    import hashlib
except ImportError:
    import md5 as hashlib

from distutils.core import Distribution, Extension
from distutils.command.build_ext import build_ext

from IPython.core import display
from IPython.core import magic_arguments
from IPython.core.magic import Magics, magics_class, cell_magic
from IPython.testing.skipdoctest import skip_doctest
from IPython.utils import py3compat

import Cython
from Cython.Compiler.Errors import CompileError
from Cython.Build.Dependencies import cythonize


@magics_class
class CythonMagics(Magics):

    def __init__(self, shell):
        super(CythonMagics,self).__init__(shell)
        self._reloads = {}
        self._code_cache = {}

    def _import_all(self, module):
        for k,v in module.__dict__.items():
            if not k.startswith('__'):
                self.shell.push({k:v})

    @cell_magic
    def cython_inline(self, line, cell):
        """Compile and run a Cython code cell using Cython.inline.

        This magic simply passes the body of the cell to Cython.inline
        and returns the result. If the variables `a` and `b` are defined
        in the user's namespace, here is a simple example that returns
        their sum::

            %%cython_inline
            return a+b

        For most purposes, we recommend the usage of the `%%cython` magic.
        """
        locs = self.shell.user_global_ns
        globs = self.shell.user_ns
        return Cython.inline(cell, locals=locs, globals=globs)

    @cell_magic
    def cython_pyximport(self, line, cell):
        """Compile and import a Cython code cell using pyximport.

        The contents of the cell are written to a `.pyx` file in the current
        working directory, which is then imported using `pyximport`. This
        magic requires a module name to be passed::

            %%cython_pyximport modulename
            def f(x):
                return 2.0*x

        The compiled module is then imported and all of its symbols are
        injected into the user's namespace. For most purposes, we recommend
        the usage of the `%%cython` magic.
        """
        module_name = line.strip()
        if not module_name:
            raise ValueError('module name must be given')
        fname = module_name + '.pyx'
        with io.open(fname, 'w', encoding='utf-8') as f:
            f.write(cell)
        if 'pyximport' not in sys.modules:
            import pyximport
            pyximport.install(reload_support=True)
        if module_name in self._reloads:
            module = self._reloads[module_name]
            reload(module)
        else:
            __import__(module_name)
            module = sys.modules[module_name]
            self._reloads[module_name] = module
        self._import_all(module)

    @magic_arguments.magic_arguments()
    @magic_arguments.argument(
        '-c', '--compile-args', action='append', default=[],
        help="Extra flags to pass to compiler via the `extra_compile_args` "
             "Extension flag (can be specified  multiple times)."
    )
    @magic_arguments.argument(
        '-la', '--link-args', action='append', default=[],
        help="Extra flags to pass to linker via the `extra_link_args` "
             "Extension flag (can be specified  multiple times)."
    )
    @magic_arguments.argument(
        '-l', '--lib', action='append', default=[],
        help="Add a library to link the extension against (can be specified "
             "multiple times)."
    )
    @magic_arguments.argument(
        '-I', '--include', action='append', default=[],
        help="Add a path to the list of include directories (can be specified "
             "multiple times)."
    )
    @magic_arguments.argument(
        '-f', '--force', action='store_true', default=False,
        help="Force the compilation of the pyx module even if it hasn't "
             "changed"
    )
    @magic_arguments.argument(
        '-a', '--annotate', action='store_true', default=False,
        help="Produce a colorized HTML version of the source. "
             "(Implies --force)."
    )
    @cell_magic
    def cython(self, line, cell):
        """Compile and import everything from a Cython code cell.

        The contents of the cell are written to a `.pyx` file in the
        directory `IPYTHONDIR/cython` using a filename with the hash of the
        code. This file is then cythonized and compiled. The resulting module
        is imported and all of its symbols are injected into the user's
        namespace. The usage is similar to that of `%%cython_pyximport` but
        you don't have to pass a module name::

        %%cython
        def f(x):
            return 2.0*x
        """
        args = magic_arguments.parse_argstring(self.cython, line)
        code = cell if cell.endswith('\n') else cell+'\n'
        lib_dir = os.path.join(self.shell.ipython_dir, 'cython')
        quiet = True
        key = code, sys.version_info, sys.executable, Cython.__version__
        module_name = "_cython_magic_" + hashlib.md5(str(key).encode('utf-8')).hexdigest()
        module_path = os.path.join(lib_dir, module_name+self.so_ext)

        if args.annotate:
            args.force = True

        if not os.path.exists(lib_dir):
            os.makedirs(lib_dir)

        if args.force or not os.path.isfile(module_path):
            c_include_dirs = args.include
            if 'numpy' in code:
                import numpy
                c_include_dirs.append(numpy.get_include())
            pyx_file = os.path.join(lib_dir, module_name + '.pyx')
            pyx_file = py3compat.cast_bytes_py2(pyx_file, encoding=sys.getfilesystemencoding())
            with io.open(pyx_file, 'w', encoding='utf-8') as f:
                f.write(code)
            extension = Extension(
                name = module_name,
                sources = [pyx_file],
                include_dirs = c_include_dirs,
                extra_compile_args = args.compile_args,
                extra_link_args = args.link_args,
                libraries = args.lib,
            )
            build_extension = self._get_build_extension()
            try:
                build_extension.extensions = cythonize([extension], quiet=quiet,
                                                       annotate=args.annotate, force=args.force)
            except CompileError:
                return
            build_extension.build_temp = os.path.dirname(pyx_file)
            build_extension.build_lib  = lib_dir
            build_extension.run()
            self._code_cache[key] = module_name

        module = imp.load_dynamic(module_name, module_path)
        self._import_all(module)

        if args.annotate:
            html_file = os.path.join(lib_dir, module_name + '.html')
            try:
                with io.open(html_file, encoding='utf-8') as f:
                    annotated_html = f.read()
            except IOError as e:
                # File could not be opened. Most likely the user has a version
                # of Cython before 0.15.1 (when `cythonize` learned the
                # `force` keyword argument) and has already compiled this
                # exact source without annotation.
                print('Cython completed successfully but the annotated '
                      'source could not be read.', file=sys.stderr)
                print(e, file=sys.stderr)
            else:
                return display.HTML(annotated_html)

    @property
    def so_ext(self):
        """The extension suffix for compiled modules."""
        try:
            return self._so_ext
        except AttributeError:
            self._so_ext = self._get_build_extension().get_ext_filename('')
            return self._so_ext

    def _get_build_extension(self):
        dist = Distribution()
        config_files = dist.find_config_files()
        try:
            config_files.remove('setup.cfg')
        except ValueError:
            pass
        dist.parse_config_files(config_files)
        build_extension = build_ext(dist)
        build_extension.finalize_options()
        return build_extension

_loaded = False

def load_ipython_extension(ip):
    """Load the extension in IPython."""
    global _loaded
    if not _loaded:
        ip.register_magics(CythonMagics)
        _loaded = True
