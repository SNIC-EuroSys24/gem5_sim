# Copyright (c) 2012 ARM Limited
# All rights reserved.
#
# The license below extends only to copyright in the software and shall
# not be construed as granting a license to any other intellectual
# property including but not limited to intellectual property relating
# to a hardware implementation of the functionality of the software
# licensed hereunder.  You may use the software subject to the license
# terms below provided that you ensure that this notice is replicated
# unmodified and in its entirety in all distributions of the software,
# modified or unmodified, in source code or in binary form.
#
# Copyright (c) 2004-2006 The Regents of The University of Michigan
# Copyright (c) 2010 Advanced Micro Devices, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Authors: Steve Reinhardt
#          Nathan Binkert
#          Andreas Hansson

import sys
from types import FunctionType, MethodType, ModuleType

import m5
from m5.util import *

# Have to import params up top since Param is referenced on initial
# load (when SimObject class references Param to create a class
# variable, the 'name' param)...
from m5.params import *
# There are a few things we need that aren't in params.__all__ since
# normal users don't need them
from m5.params import ParamDesc, VectorParamDesc, \
     isNullPointer, SimObjectVector, Port

from m5.proxy import *
from m5.proxy import isproxy

#####################################################################
#
# M5 Python Configuration Utility
#
# The basic idea is to write simple Python programs that build Python
# objects corresponding to M5 SimObjects for the desired simulation
# configuration.  For now, the Python emits a .ini file that can be
# parsed by M5.  In the future, some tighter integration between M5
# and the Python interpreter may allow bypassing the .ini file.
#
# Each SimObject class in M5 is represented by a Python class with the
# same name.  The Python inheritance tree mirrors the M5 C++ tree
# (e.g., SimpleCPU derives from BaseCPU in both cases, and all
# SimObjects inherit from a single SimObject base class).  To specify
# an instance of an M5 SimObject in a configuration, the user simply
# instantiates the corresponding Python object.  The parameters for
# that SimObject are given by assigning to attributes of the Python
# object, either using keyword assignment in the constructor or in
# separate assignment statements.  For example:
#
# cache = BaseCache(size='64KB')
# cache.hit_latency = 3
# cache.assoc = 8
#
# The magic lies in the mapping of the Python attributes for SimObject
# classes to the actual SimObject parameter specifications.  This
# allows parameter validity checking in the Python code.  Continuing
# the example above, the statements "cache.blurfl=3" or
# "cache.assoc='hello'" would both result in runtime errors in Python,
# since the BaseCache object has no 'blurfl' parameter and the 'assoc'
# parameter requires an integer, respectively.  This magic is done
# primarily by overriding the special __setattr__ method that controls
# assignment to object attributes.
#
# Once a set of Python objects have been instantiated in a hierarchy,
# calling 'instantiate(obj)' (where obj is the root of the hierarchy)
# will generate a .ini file.
#
#####################################################################

# list of all SimObject classes
allClasses = {}

# dict to look up SimObjects based on path
instanceDict = {}

def public_value(key, value):
    return key.startswith('_') or \
               isinstance(value, (FunctionType, MethodType, ModuleType,
                                  classmethod, type))

# The metaclass for SimObject.  This class controls how new classes
# that derive from SimObject are instantiated, and provides inherited
# class behavior (just like a class controls how instances of that
# class are instantiated, and provides inherited instance behavior).
class MetaSimObject(type):
    # Attributes that can be set only at initialization time
    init_keywords = { 'abstract' : bool,
                      'cxx_class' : str,
                      'cxx_type' : str,
                      'type' : str }
    # Attributes that can be set any time
    keywords = { 'check' : FunctionType }

    # __new__ is called before __init__, and is where the statements
    # in the body of the class definition get loaded into the class's
    # __dict__.  We intercept this to filter out parameter & port assignments
    # and only allow "private" attributes to be passed to the base
    # __new__ (starting with underscore).
    def __new__(mcls, name, bases, dict):
        assert name not in allClasses, "SimObject %s already present" % name

        # Copy "private" attributes, functions, and classes to the
        # official dict.  Everything else goes in _init_dict to be
        # filtered in __init__.
        cls_dict = {}
        value_dict = {}
        for key,val in dict.items():
            if public_value(key, val):
                cls_dict[key] = val
            else:
                # must be a param/port setting
                value_dict[key] = val
        if 'abstract' not in value_dict:
            value_dict['abstract'] = False
        cls_dict['_value_dict'] = value_dict
        cls = super(MetaSimObject, mcls).__new__(mcls, name, bases, cls_dict)
        if 'type' in value_dict:
            allClasses[name] = cls
        return cls

    # subclass initialization
    def __init__(cls, name, bases, dict):
        # calls type.__init__()... I think that's a no-op, but leave
        # it here just in case it's not.
        super(MetaSimObject, cls).__init__(name, bases, dict)

        # initialize required attributes

        # class-only attributes
        cls._params = multidict() # param descriptions
        cls._ports = multidict()  # port descriptions

        # class or instance attributes
        cls._values = multidict()   # param values
        cls._children = multidict() # SimObject children
        cls._port_refs = multidict() # port ref objects
        cls._instantiated = False # really instantiated, cloned, or subclassed

        # We don't support multiple inheritance of sim objects.  If you want
        # to, you must fix multidict to deal with it properly. Non sim-objects
        # are ok, though
        bTotal = 0
        for c in bases:
            if isinstance(c, MetaSimObject):
                bTotal += 1
            if bTotal > 1:
                raise TypeError, "SimObjects do not support multiple inheritance"

        base = bases[0]

        # Set up general inheritance via multidicts.  A subclass will
        # inherit all its settings from the base class.  The only time
        # the following is not true is when we define the SimObject
        # class itself (in which case the multidicts have no parent).
        if isinstance(base, MetaSimObject):
            cls._base = base
            cls._params.parent = base._params
            cls._ports.parent = base._ports
            cls._values.parent = base._values
            cls._children.parent = base._children
            cls._port_refs.parent = base._port_refs
            # mark base as having been subclassed
            base._instantiated = True
        else:
            cls._base = None

        # default keyword values
        if 'type' in cls._value_dict:
            if 'cxx_class' not in cls._value_dict:
                cls._value_dict['cxx_class'] = cls._value_dict['type']

            cls._value_dict['cxx_type'] = '%s *' % cls._value_dict['cxx_class']

        # Export methods are automatically inherited via C++, so we
        # don't want the method declarations to get inherited on the
        # python side (and thus end up getting repeated in the wrapped
        # versions of derived classes).  The code below basicallly
        # suppresses inheritance by substituting in the base (null)
        # versions of these methods unless a different version is
        # explicitly supplied.
        for method_name in ('export_methods', 'export_method_cxx_predecls',
                            'export_method_swig_predecls'):
            if method_name not in cls.__dict__:
                base_method = getattr(MetaSimObject, method_name)
                m = MethodType(base_method, cls, MetaSimObject)
                setattr(cls, method_name, m)

        # Now process the _value_dict items.  They could be defining
        # new (or overriding existing) parameters or ports, setting
        # class keywords (e.g., 'abstract'), or setting parameter
        # values or port bindings.  The first 3 can only be set when
        # the class is defined, so we handle them here.  The others
        # can be set later too, so just emulate that by calling
        # setattr().
        for key,val in cls._value_dict.items():
            # param descriptions
            if isinstance(val, ParamDesc):
                cls._new_param(key, val)

            # port objects
            elif isinstance(val, Port):
                cls._new_port(key, val)

            # init-time-only keywords
            elif cls.init_keywords.has_key(key):
                cls._set_keyword(key, val, cls.init_keywords[key])

            # default: use normal path (ends up in __setattr__)
            else:
                setattr(cls, key, val)

    def _set_keyword(cls, keyword, val, kwtype):
        if not isinstance(val, kwtype):
            raise TypeError, 'keyword %s has bad type %s (expecting %s)' % \
                  (keyword, type(val), kwtype)
        if isinstance(val, FunctionType):
            val = classmethod(val)
        type.__setattr__(cls, keyword, val)

    def _new_param(cls, name, pdesc):
        # each param desc should be uniquely assigned to one variable
        assert(not hasattr(pdesc, 'name'))
        pdesc.name = name
        cls._params[name] = pdesc
        if hasattr(pdesc, 'default'):
            cls._set_param(name, pdesc.default, pdesc)

    def _set_param(cls, name, value, param):
        assert(param.name == name)
        try:
            value = param.convert(value)
        except Exception, e:
            msg = "%s\nError setting param %s.%s to %s\n" % \
                  (e, cls.__name__, name, value)
            e.args = (msg, )
            raise
        cls._values[name] = value
        # if param value is a SimObject, make it a child too, so that
        # it gets cloned properly when the class is instantiated
        if isSimObjectOrVector(value) and not value.has_parent():
            cls._add_cls_child(name, value)

    def _add_cls_child(cls, name, child):
        # It's a little funky to have a class as a parent, but these
        # objects should never be instantiated (only cloned, which
        # clears the parent pointer), and this makes it clear that the
        # object is not an orphan and can provide better error
        # messages.
        child.set_parent(cls, name)
        cls._children[name] = child

    def _new_port(cls, name, port):
        # each port should be uniquely assigned to one variable
        assert(not hasattr(port, 'name'))
        port.name = name
        cls._ports[name] = port

    # same as _get_port_ref, effectively, but for classes
    def _cls_get_port_ref(cls, attr):
        # Return reference that can be assigned to another port
        # via __setattr__.  There is only ever one reference
        # object per port, but we create them lazily here.
        ref = cls._port_refs.get(attr)
        if not ref:
            ref = cls._ports[attr].makeRef(cls)
            cls._port_refs[attr] = ref
        return ref

    # Set attribute (called on foo.attr = value when foo is an
    # instance of class cls).
    def __setattr__(cls, attr, value):
        # normal processing for private attributes
        if public_value(attr, value):
            type.__setattr__(cls, attr, value)
            return

        if cls.keywords.has_key(attr):
            cls._set_keyword(attr, value, cls.keywords[attr])
            return

        if cls._ports.has_key(attr):
            cls._cls_get_port_ref(attr).connect(value)
            return

        if isSimObjectOrSequence(value) and cls._instantiated:
            raise RuntimeError, \
                  "cannot set SimObject parameter '%s' after\n" \
                  "    class %s has been instantiated or subclassed" \
                  % (attr, cls.__name__)

        # check for param
        param = cls._params.get(attr)
        if param:
            cls._set_param(attr, value, param)
            return

        if isSimObjectOrSequence(value):
            # If RHS is a SimObject, it's an implicit child assignment.
            cls._add_cls_child(attr, coerceSimObjectOrVector(value))
            return

        # no valid assignment... raise exception
        raise AttributeError, \
              "Class %s has no parameter \'%s\'" % (cls.__name__, attr)

    def __getattr__(cls, attr):
        if attr == 'cxx_class_path':
            return cls.cxx_class.split('::')

        if attr == 'cxx_class_name':
            return cls.cxx_class_path[-1]

        if attr == 'cxx_namespaces':
            return cls.cxx_class_path[:-1]

        if cls._values.has_key(attr):
            return cls._values[attr]

        if cls._children.has_key(attr):
            return cls._children[attr]

        raise AttributeError, \
              "object '%s' has no attribute '%s'" % (cls.__name__, attr)

    def __str__(cls):
        return cls.__name__

    # See ParamValue.cxx_predecls for description.
    def cxx_predecls(cls, code):
        code('#include "params/$cls.hh"')

    # See ParamValue.swig_predecls for description.
    def swig_predecls(cls, code):
        code('%import "python/m5/internal/param_$cls.i"')

    # Hook for exporting additional C++ methods to Python via SWIG.
    # Default is none, override using @classmethod in class definition.
    def export_methods(cls, code):
        pass

    # Generate the code needed as a prerequisite for the C++ methods
    # exported via export_methods() to be compiled in the _wrap.cc
    # file.  Typically generates one or more #include statements.  If
    # any methods are exported, typically at least the C++ header
    # declaring the relevant SimObject class must be included.
    def export_method_cxx_predecls(cls, code):
        pass

    # Generate the code needed as a prerequisite for the C++ methods
    # exported via export_methods() to be processed by SWIG.
    # Typically generates one or more %include or %import statements.
    # If any methods are exported, typically at least the C++ header
    # declaring the relevant SimObject class must be included.
    def export_method_swig_predecls(cls, code):
        pass

    # Generate the declaration for this object for wrapping with SWIG.
    # Generates code that goes into a SWIG .i file.  Called from
    # src/SConscript.
    def swig_decl(cls, code):
        class_path = cls.cxx_class.split('::')
        classname = class_path[-1]
        namespaces = class_path[:-1]

        # The 'local' attribute restricts us to the params declared in
        # the object itself, not including inherited params (which
        # will also be inherited from the base class's param struct
        # here).
        params = cls._params.local.values()
        ports = cls._ports.local

        code('%module(package="m5.internal") param_$cls')
        code()
        code('%{')
        code('#include "params/$cls.hh"')
        for param in params:
            param.cxx_predecls(code)
        cls.export_method_cxx_predecls(code)
        code('''\
/**
  * This is a workaround for bug in swig. Prior to gcc 4.6.1 the STL
  * headers like vector, string, etc. used to automatically pull in
  * the cstddef header but starting with gcc 4.6.1 they no longer do.
  * This leads to swig generated a file that does not compile so we
  * explicitly include cstddef. Additionally, including version 2.0.4,
  * swig uses ptrdiff_t without the std:: namespace prefix which is
  * required with gcc 4.6.1. We explicitly provide access to it.
  */
#include <cstddef>
using std::ptrdiff_t;
''')
        code('%}')
        code()

        for param in params:
            param.swig_predecls(code)
        cls.export_method_swig_predecls(code)

        code()
        if cls._base:
            code('%import "python/m5/internal/param_${{cls._base}}.i"')
        code()

        for ns in namespaces:
            code('namespace $ns {')

        if namespaces:
            code('// avoid name conflicts')
            sep_string = '_COLONS_'
            flat_name = sep_string.join(class_path)
            code('%rename($flat_name) $classname;')

        code()
        code('// stop swig from creating/wrapping default ctor/dtor')
        code('%nodefault $classname;')
        code('class $classname')
        if cls._base:
            code('    : public ${{cls._base.cxx_class}}')
        code('{')
        code('  public:')
        cls.export_methods(code)
        code('};')

        for ns in reversed(namespaces):
            code('} // namespace $ns')

        code()
        code('%include "params/$cls.hh"')


    # Generate the C++ declaration (.hh file) for this SimObject's
    # param struct.  Called from src/SConscript.
    def cxx_param_decl(cls, code):
        # The 'local' attribute restricts us to the params declared in
        # the object itself, not including inherited params (which
        # will also be inherited from the base class's param struct
        # here).
        params = cls._params.local.values()
        ports = cls._ports.local
        try:
            ptypes = [p.ptype for p in params]
        except:
            print cls, p, p.ptype_str
            print params
            raise

        class_path = cls._value_dict['cxx_class'].split('::')

        code('''\
#ifndef __PARAMS__${cls}__
#define __PARAMS__${cls}__

''')

        # A forward class declaration is sufficient since we are just
        # declaring a pointer.
        for ns in class_path[:-1]:
            code('namespace $ns {')
        code('class $0;', class_path[-1])
        for ns in reversed(class_path[:-1]):
            code('} // namespace $ns')
        code()

        # The base SimObject has a couple of params that get
        # automatically set from Python without being declared through
        # the normal Param mechanism; we slip them in here (needed
        # predecls now, actual declarations below)
        if cls == SimObject:
            code('''
#ifndef PY_VERSION
struct PyObject;
#endif

#include <string>

class EventQueue;
''')
        for param in params:
            param.cxx_predecls(code)
        for port in ports.itervalues():
            port.cxx_predecls(code)
        code()

        if cls._base:
            code('#include "params/${{cls._base.type}}.hh"')
            code()

        for ptype in ptypes:
            if issubclass(ptype, Enum):
                code('#include "enums/${{ptype.__name__}}.hh"')
                code()

        # now generate the actual param struct
        code("struct ${cls}Params")
        if cls._base:
            code("    : public ${{cls._base.type}}Params")
        code("{")
        if not hasattr(cls, 'abstract') or not cls.abstract:
            if 'type' in cls.__dict__:
                code("    ${{cls.cxx_type}} create();")

        code.indent()
        if cls == SimObject:
            code('''
    SimObjectParams()
    {
        extern EventQueue mainEventQueue;
        eventq = &mainEventQueue;
    }
    virtual ~SimObjectParams() {}

    std::string name;
    PyObject *pyobj;
    EventQueue *eventq;
            ''')
        for param in params:
            param.cxx_decl(code)
        for port in ports.itervalues():
            port.cxx_decl(code)

        code.dedent()
        code('};')

        code()
        code('#endif // __PARAMS__${cls}__')
        return code



# The SimObject class is the root of the special hierarchy.  Most of
# the code in this class deals with the configuration hierarchy itself
# (parent/child node relationships).
class SimObject(object):
    # Specify metaclass.  Any class inheriting from SimObject will
    # get this metaclass.
    __metaclass__ = MetaSimObject
    type = 'SimObject'
    abstract = True

    @classmethod
    def export_method_cxx_predecls(cls, code):
        code('''
#include <Python.h>

#include "sim/serialize.hh"
#include "sim/sim_object.hh"
''')

    @classmethod
    def export_method_swig_predecls(cls, code):
        code('''
%include <std_string.i>
''')

    @classmethod
    def export_methods(cls, code):
        code('''
    enum State {
      Running,
      Draining,
      Drained
    };

    void init();
    void loadState(Checkpoint *cp);
    void initState();
    void regStats();
    void resetStats();
    void startup();

    unsigned int drain(Event *drain_event);
    void resume();
    void switchOut();
    void takeOverFrom(BaseCPU *cpu);
''')

    # Initialize new instance.  For objects with SimObject-valued
    # children, we need to recursively clone the classes represented
    # by those param values as well in a consistent "deep copy"-style
    # fashion.  That is, we want to make sure that each instance is
    # cloned only once, and that if there are multiple references to
    # the same original object, we end up with the corresponding
    # cloned references all pointing to the same cloned instance.
    def __init__(self, **kwargs):
        ancestor = kwargs.get('_ancestor')
        memo_dict = kwargs.get('_memo')
        if memo_dict is None:
            # prepare to memoize any recursively instantiated objects
            memo_dict = {}
        elif ancestor:
            # memoize me now to avoid problems with recursive calls
            memo_dict[ancestor] = self

        if not ancestor:
            ancestor = self.__class__
        ancestor._instantiated = True

        # initialize required attributes
        self._parent = None
        self._name = None
        self._ccObject = None  # pointer to C++ object
        self._ccParams = None
        self._instantiated = False # really "cloned"

        # Clone children specified at class level.  No need for a
        # multidict here since we will be cloning everything.
        # Do children before parameter values so that children that
        # are also param values get cloned properly.
        self._children = {}
        for key,val in ancestor._children.iteritems():
            self.add_child(key, val(_memo=memo_dict))

        # Inherit parameter values from class using multidict so
        # individual value settings can be overridden but we still
        # inherit late changes to non-overridden class values.
        self._values = multidict(ancestor._values)
        # clone SimObject-valued parameters
        for key,val in ancestor._values.iteritems():
            val = tryAsSimObjectOrVector(val)
            if val is not None:
                self._values[key] = val(_memo=memo_dict)

        # clone port references.  no need to use a multidict here
        # since we will be creating new references for all ports.
        self._port_refs = {}
        for key,val in ancestor._port_refs.iteritems():
            self._port_refs[key] = val.clone(self, memo_dict)
        # apply attribute assignments from keyword args, if any
        for key,val in kwargs.iteritems():
            setattr(self, key, val)

    # "Clone" the current instance by creating another instance of
    # this instance's class, but that inherits its parameter values
    # and port mappings from the current instance.  If we're in a
    # "deep copy" recursive clone, check the _memo dict to see if
    # we've already cloned this instance.
    def __call__(self, **kwargs):
        memo_dict = kwargs.get('_memo')
        if memo_dict is None:
            # no memo_dict: must be top-level clone operation.
            # this is only allowed at the root of a hierarchy
            if self._parent:
                raise RuntimeError, "attempt to clone object %s " \
                      "not at the root of a tree (parent = %s)" \
                      % (self, self._parent)
            # create a new dict and use that.
            memo_dict = {}
            kwargs['_memo'] = memo_dict
        elif memo_dict.has_key(self):
            # clone already done & memoized
            return memo_dict[self]
        return self.__class__(_ancestor = self, **kwargs)

    def _get_port_ref(self, attr):
        # Return reference that can be assigned to another port
        # via __setattr__.  There is only ever one reference
        # object per port, but we create them lazily here.
        ref = self._port_refs.get(attr)
        if not ref:
            ref = self._ports[attr].makeRef(self)
            self._port_refs[attr] = ref
        return ref

    def __getattr__(self, attr):
        if self._ports.has_key(attr):
            return self._get_port_ref(attr)

        if self._values.has_key(attr):
            return self._values[attr]

        if self._children.has_key(attr):
            return self._children[attr]

        # If the attribute exists on the C++ object, transparently
        # forward the reference there.  This is typically used for
        # SWIG-wrapped methods such as init(), regStats(),
        # resetStats(), startup(), drain(), and
        # resume().
        if self._ccObject and hasattr(self._ccObject, attr):
            return getattr(self._ccObject, attr)

        raise AttributeError, "object '%s' has no attribute '%s'" \
              % (self.__class__.__name__, attr)

    # Set attribute (called on foo.attr = value when foo is an
    # instance of class cls).
    def __setattr__(self, attr, value):
        # normal processing for private attributes
        if attr.startswith('_'):
            object.__setattr__(self, attr, value)
            return

        if self._ports.has_key(attr):
            # set up port connection
            self._get_port_ref(attr).connect(value)
            return

        if isSimObjectOrSequence(value) and self._instantiated:
            raise RuntimeError, \
                  "cannot set SimObject parameter '%s' after\n" \
                  "    instance been cloned %s" % (attr, `self`)

        param = self._params.get(attr)
        if param:
            try:
                value = param.convert(value)
            except Exception, e:
                msg = "%s\nError setting param %s.%s to %s\n" % \
                      (e, self.__class__.__name__, attr, value)
                e.args = (msg, )
                raise
            self._values[attr] = value
            # implicitly parent unparented objects assigned as params
            if isSimObjectOrVector(value) and not value.has_parent():
                self.add_child(attr, value)
            return

        # if RHS is a SimObject, it's an implicit child assignment
        if isSimObjectOrSequence(value):
            self.add_child(attr, value)
            return

        # no valid assignment... raise exception
        raise AttributeError, "Class %s has no parameter %s" \
              % (self.__class__.__name__, attr)


    # this hack allows tacking a '[0]' onto parameters that may or may
    # not be vectors, and always getting the first element (e.g. cpus)
    def __getitem__(self, key):
        if key == 0:
            return self
        raise TypeError, "Non-zero index '%s' to SimObject" % key

    # Also implemented by SimObjectVector
    def clear_parent(self, old_parent):
        assert self._parent is old_parent
        self._parent = None

    # Also implemented by SimObjectVector
    def set_parent(self, parent, name):
        self._parent = parent
        self._name = name

    # Also implemented by SimObjectVector
    def get_name(self):
        return self._name

    # Also implemented by SimObjectVector
    def has_parent(self):
        return self._parent is not None

    # clear out child with given name. This code is not likely to be exercised.
    # See comment in add_child.
    def clear_child(self, name):
        child = self._children[name]
        child.clear_parent(self)
        del self._children[name]

    # Add a new child to this object.
    def add_child(self, name, child):
        child = coerceSimObjectOrVector(child)
        if child.has_parent():
            print "warning: add_child('%s'): child '%s' already has parent" % \
                  (name, child.get_name())
        if self._children.has_key(name):
            # This code path had an undiscovered bug that would make it fail
            # at runtime. It had been here for a long time and was only
            # exposed by a buggy script. Changes here will probably not be
            # exercised without specialized testing.
            self.clear_child(name)
        child.set_parent(self, name)
        self._children[name] = child

    # Take SimObject-valued parameters that haven't been explicitly
    # assigned as children and make them children of the object that
    # they were assigned to as a parameter value.  This guarantees
    # that when we instantiate all the parameter objects we're still
    # inside the configuration hierarchy.
    def adoptOrphanParams(self):
        for key,val in self._values.iteritems():
            if not isSimObjectVector(val) and isSimObjectSequence(val):
                # need to convert raw SimObject sequences to
                # SimObjectVector class so we can call has_parent()
                val = SimObjectVector(val)
                self._values[key] = val
            if isSimObjectOrVector(val) and not val.has_parent():
                print "warning: %s adopting orphan SimObject param '%s'" \
                      % (self, key)
                self.add_child(key, val)

    def path(self):
        if not self._parent:
            return '<orphan %s>' % self.__class__
        ppath = self._parent.path()
        if ppath == 'root':
            return self._name
        return ppath + "." + self._name

    def __str__(self):
        return self.path()

    def ini_str(self):
        return self.path()

    def find_any(self, ptype):
        if isinstance(self, ptype):
            return self, True

        found_obj = None
        for child in self._children.itervalues():
            if isinstance(child, ptype):
                if found_obj != None and child != found_obj:
                    raise AttributeError, \
                          'parent.any matched more than one: %s %s' % \
                          (found_obj.path, child.path)
                found_obj = child
        # search param space
        for pname,pdesc in self._params.iteritems():
            if issubclass(pdesc.ptype, ptype):
                match_obj = self._values[pname]
                if found_obj != None and found_obj != match_obj:
                    raise AttributeError, \
                          'parent.any matched more than one: %s and %s' % (found_obj.path, match_obj.path)
                found_obj = match_obj
        return found_obj, found_obj != None

    def find_all(self, ptype):
        all = {}
        # search children
        for child in self._children.itervalues():
            if isinstance(child, ptype) and not isproxy(child) and \
               not isNullPointer(child):
                all[child] = True
            if isSimObject(child):
                # also add results from the child itself
                child_all, done = child.find_all(ptype)
                all.update(dict(zip(child_all, [done] * len(child_all))))
        # search param space
        for pname,pdesc in self._params.iteritems():
            if issubclass(pdesc.ptype, ptype):
                match_obj = self._values[pname]
                if not isproxy(match_obj) and not isNullPointer(match_obj):
                    all[match_obj] = True
        return all.keys(), True

    def unproxy(self, base):
        return self

    def unproxyParams(self):
        for param in self._params.iterkeys():
            value = self._values.get(param)
            if value != None and isproxy(value):
                try:
                    value = value.unproxy(self)
                except:
                    print "Error in unproxying param '%s' of %s" % \
                          (param, self.path())
                    raise
                setattr(self, param, value)

        # Unproxy ports in sorted order so that 'append' operations on
        # vector ports are done in a deterministic fashion.
        port_names = self._ports.keys()
        port_names.sort()
        for port_name in port_names:
            port = self._port_refs.get(port_name)
            if port != None:
                port.unproxy(self)

    def print_ini(self, ini_file):
        print >>ini_file, '[' + self.path() + ']'       # .ini section header

        instanceDict[self.path()] = self

        if hasattr(self, 'type'):
            print >>ini_file, 'type=%s' % self.type

        if len(self._children.keys()):
            print >>ini_file, 'children=%s' % \
                  ' '.join(self._children[n].get_name() \
                  for n in sorted(self._children.keys()))

        for param in sorted(self._params.keys()):
            value = self._values.get(param)
            if value != None:
                print >>ini_file, '%s=%s' % (param,
                                             self._values[param].ini_str())

        for port_name in sorted(self._ports.keys()):
            port = self._port_refs.get(port_name, None)
            if port != None:
                print >>ini_file, '%s=%s' % (port_name, port.ini_str())

        print >>ini_file        # blank line between objects

    # generate a tree of dictionaries expressing all the parameters in the
    # instantiated system for use by scripts that want to do power, thermal
    # visualization, and other similar tasks
    def get_config_as_dict(self):
        d = attrdict()
        if hasattr(self, 'type'):
            d.type = self.type
        if hasattr(self, 'cxx_class'):
            d.cxx_class = self.cxx_class
        # Add the name and path of this object to be able to link to
        # the stats
        d.name = self.get_name()
        d.path = self.path()

        for param in sorted(self._params.keys()):
            value = self._values.get(param)
            if value != None:
                try:
                    # Use native type for those supported by JSON and
                    # strings for everything else. skipkeys=True seems
                    # to not work as well as one would hope
                    if type(self._values[param].value) in \
                            [str, unicode, int, long, float, bool, None]:
                        d[param] = self._values[param].value
                    else:
                        d[param] = str(self._values[param])

                except AttributeError:
                    pass

        for n in sorted(self._children.keys()):
            child = self._children[n]
            # Use the name of the attribute (and not get_name()) as
            # the key in the JSON dictionary to capture the hierarchy
            # in the Python code that assembled this system
            d[n] = child.get_config_as_dict()

        for port_name in sorted(self._ports.keys()):
            port = self._port_refs.get(port_name, None)
            if port != None:
                # Represent each port with a dictionary containing the
                # prominent attributes
                d[port_name] = port.get_config_as_dict()

        return d

    def getCCParams(self):
        if self._ccParams:
            return self._ccParams

        cc_params_struct = getattr(m5.internal.params, '%sParams' % self.type)
        cc_params = cc_params_struct()
        cc_params.pyobj = self
        cc_params.name = str(self)

        param_names = self._params.keys()
        param_names.sort()
        for param in param_names:
            value = self._values.get(param)
            if value is None:
                fatal("%s.%s without default or user set value",
                      self.path(), param)

            value = value.getValue()
            if isinstance(self._params[param], VectorParamDesc):
                assert isinstance(value, list)
                vec = getattr(cc_params, param)
                assert not len(vec)
                for v in value:
                    vec.append(v)
            else:
                setattr(cc_params, param, value)

        port_names = self._ports.keys()
        port_names.sort()
        for port_name in port_names:
            port = self._port_refs.get(port_name, None)
            if port != None:
                port_count = len(port)
            else:
                port_count = 0
            setattr(cc_params, 'port_' + port_name + '_connection_count',
                    port_count)
        self._ccParams = cc_params
        return self._ccParams

    # Get C++ object corresponding to this object, calling C++ if
    # necessary to construct it.  Does *not* recursively create
    # children.
    def getCCObject(self):
        if not self._ccObject:
            # Make sure this object is in the configuration hierarchy
            if not self._parent and not isRoot(self):
                raise RuntimeError, "Attempt to instantiate orphan node"
            # Cycles in the configuration hierarchy are not supported. This
            # will catch the resulting recursion and stop.
            self._ccObject = -1
            params = self.getCCParams()
            self._ccObject = params.create()
        elif self._ccObject == -1:
            raise RuntimeError, "%s: Cycle found in configuration hierarchy." \
                  % self.path()
        return self._ccObject

    def descendants(self):
        yield self
        for child in self._children.itervalues():
            for obj in child.descendants():
                yield obj

    # Call C++ to create C++ object corresponding to this object
    def createCCObject(self):
        self.getCCParams()
        self.getCCObject() # force creation

    def getValue(self):
        return self.getCCObject()

    # Create C++ port connections corresponding to the connections in
    # _port_refs
    def connectPorts(self):
        for portRef in self._port_refs.itervalues():
            portRef.ccConnect()

    def getMemoryMode(self):
        if not isinstance(self, m5.objects.System):
            return None

        return self._ccObject.getMemoryMode()

    def changeTiming(self, mode):
        if isinstance(self, m5.objects.System):
            # i don't know if there's a better way to do this - calling
            # setMemoryMode directly from self._ccObject results in calling
            # SimObject::setMemoryMode, not the System::setMemoryMode
            self._ccObject.setMemoryMode(mode)

    def takeOverFrom(self, old_cpu):
        self._ccObject.takeOverFrom(old_cpu._ccObject)

# Function to provide to C++ so it can look up instances based on paths
def resolveSimObject(name):
    obj = instanceDict[name]
    return obj.getCCObject()

def isSimObject(value):
    return isinstance(value, SimObject)

def isSimObjectClass(value):
    return issubclass(value, SimObject)

def isSimObjectVector(value):
    return isinstance(value, SimObjectVector)

def isSimObjectSequence(value):
    if not isinstance(value, (list, tuple)) or len(value) == 0:
        return False

    for val in value:
        if not isNullPointer(val) and not isSimObject(val):
            return False

    return True

def isSimObjectOrSequence(value):
    return isSimObject(value) or isSimObjectSequence(value)

def isRoot(obj):
    from m5.objects import Root
    return obj and obj is Root.getInstance()

def isSimObjectOrVector(value):
    return isSimObject(value) or isSimObjectVector(value)

def tryAsSimObjectOrVector(value):
    if isSimObjectOrVector(value):
        return value
    if isSimObjectSequence(value):
        return SimObjectVector(value)
    return None

def coerceSimObjectOrVector(value):
    value = tryAsSimObjectOrVector(value)
    if value is None:
        raise TypeError, "SimObject or SimObjectVector expected"
    return value

baseClasses = allClasses.copy()
baseInstances = instanceDict.copy()

def clear():
    global allClasses, instanceDict

    allClasses = baseClasses.copy()
    instanceDict = baseInstances.copy()

# __all__ defines the list of symbols that get exported when
# 'from config import *' is invoked.  Try to keep this reasonably
# short to avoid polluting other namespaces.
__all__ = [ 'SimObject' ]
