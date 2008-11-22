#!/usr/bin/python

"""This file runs the test suite against several versions of SQLite
and Python to make sure everything is ok in the various combinations.
It only runs on a UNIX like environment.

You should make sure that wget is using a proxy so you don't hit the
upstream sites repeatedly and have ccache so that compiles are
quicker.

All the work is done in parallel rather than serially.  This allows
for it to finish a lot sooner.

"""

import os
import re
import sys
import threading
import Queue
import optparse

def run(cmd):
    status=os.system(cmd)
    if os.WIFEXITED(status):
        code=os.WEXITSTATUS(status)
        if code==0:
            return
        raise Exception("Exited with code "+`code`+": "+cmd)
    raise Exception("Failed with signal "+`os.WTERMSIG(status)`+": "+cmd)


def dotest(logdir, pybin, pylib, workdir, sqlitever):
    buildsqlite(workdir, sqlitever, os.path.abspath(os.path.join(logdir, "sqlitebuild.txt")))
    buildapsw(os.path.abspath(os.path.join(logdir, "buildapsw.txt")), pybin, workdir)
    # now the actual tests
    run("cd %s ; env LD_LIBRARY_PATH=%s %s tests.py -v >%s 2>&1" % (workdir, pylib, pybin, os.path.abspath(os.path.join(logdir, "runtests.txt"))))


def runtest(workdir, pyver, ucs, sqlitever, logdir):
    pybin, pylib=buildpython(workdir, pyver, ucs, os.path.abspath(os.path.join(logdir, "pybuild.txt")))
    dotest(logdir, pybin, pylib, workdir, sqlitever)

def threadrun(queue):
    while True:
        d=queue.get()
        if d is None:
            return
        try:
            runtest(**d)
            sys.stdout.write(".")
            sys.stdout.flush()
        except:
            print "\nFAILED", d
        
def main(PYVERS, UCSTEST, SQLITEVERS, concurrency):
    print "Test starting"
    os.system("rm -rf apsw.so megatestresults 2>/dev/null ; mkdir megatestresults")
    print "  ... removing old work directory"
    workdir=os.path.abspath("work")
    os.system("rm -rf %s 2>/dev/null ; mkdir %s" % (workdir, workdir))
    os.system('rm -rf $HOME/.local/lib/python*/site-packages/apsw* 2>/dev/null')
    print "      done"

    queue=Queue.Queue()
    threads=[]

    for pyver in PYVERS:
        for ucs in UCSTEST:
            if pyver=="system":
                if ucs!=2: continue
                ucs=0
            for sqlitever in SQLITEVERS:
                print "Python",pyver,"ucs",ucs,"   SQLite",sqlitever
                workdir=os.path.abspath(os.path.join("work", "py%s-ucs%d-sq%s" % (pyver, ucs, sqlitever)))
                logdir=os.path.abspath(os.path.join("megatestresults", "py%s-ucs%d-sq%s" % (pyver, ucs, sqlitever)))
                run("mkdir -p %s/src %s" % (workdir, logdir))
                run("cp *.py "+workdir)
                run("cp src/*.c src/*.h "+workdir+"/src/")

                queue.put({'workdir': workdir, 'pyver': pyver, 'ucs': ucs, 'sqlitever': sqlitever, 'logdir': logdir})

    threads=[]
    for i in range(concurrency):
        queue.put(None) # exit sentinel
        t=threading.Thread(target=threadrun, args=(queue,))
        t.start()
        threads.append(t)

    print "All builds started, now waiting for them to finish (%d concurrency)" % (concurrency,)
    for t in threads:
        t.join()
    print "\nFinished"


def getpyurl(pyver):
    dirver=pyver
    if 'b' in dirver:
        dirver=dirver.split('b')[0]
    elif 'rc' in dirver:
        dirver=dirver.split('rc')[0]
    if pyver>'2.3.0':
        return "http://python.org/ftp/python/%s/Python-%s.tar.bz2" % (dirver,pyver)
    if pyver=='2.3.0':
        pyver='2.3'
        dirver='2.3'
    return "http://python.org/ftp/python/%s/Python-%s.tgz" % (dirver,pyver)

def sqliteurl(sqlitever):
    return "http://sqlite.org/sqlite-amalgamation-%s.zip" % (sqlitever.replace('.', '_'),)

def buildpython(workdir, pyver, ucs, logfilename):
    if pyver=="system": return "/usr/bin/python", ""
    url=getpyurl(pyver)
    if url.endswith(".bz2"):
        tarx="j"
    else:
        tarx="z"
    if pyver=="2.3.0": pyver="2.3"    
    run("cd %s ; mkdir pyinst ; wget -q %s -O - | tar xf%s -  > %s 2>&1" % (workdir, url, tarx, logfilename))
    # See https://bugs.launchpad.net/ubuntu/+source/gcc-defaults/+bug/286334
    if pyver.startswith("2.3"):
        # https://bugs.launchpad.net/bugs/286334
        opt='BASECFLAGS=-U_FORTIFY_SOURCE'
    else:
        opt=''
    run("cd %s ; cd Python-%s ; ./configure %s --disable-ipv6 --enable-unicode=ucs%d --prefix=%s/pyinst  >> %s 2>&1; make >>%s 2>&1; make  install >>%s 2>&1" % (workdir, pyver, opt, ucs, workdir, logfilename, logfilename, logfilename))
    suf=""
    if pyver>="3.0":
        suf="3.0"
    return os.path.join(workdir, "pyinst", "bin", "python"+suf), os.path.join(workdir, "pyinst", "lib")
    
def buildsqlite(workdir, sqlitever, logfile):
    os.system("rm -rf '%s/sqlite3' '%s/sqlite3.c' 2>/dev/null" % (workdir,workdir))
    if sqlitever=="cvs":
        run("cd %s ; cvs -d :pserver:anonymous@www.sqlite.org:/sqlite checkout sqlite > %s 2>&1; mv sqlite sqlite3" % (workdir, logfile,))
        run('( set -x ; cd %s/sqlite3 ; ./configure --enable-loadextension --enable-threadsafe --disable-tcl ; make sqlite3.c ; cp src/sqlite3ext.h . ) >> %s 2>&1' % (workdir,logfile))
    else:
        run("cd %s ; mkdir sqlite3 ; cd sqlite3 ; wget -q %s ; unzip -q %s " % (workdir, sqliteurl(sqlitever), os.path.basename(sqliteurl(sqlitever))))
    if sys.platform.startswith("darwin"):
        run('cd %s ; gcc -fPIC -bundle -o testextension.sqlext -Isqlite3 -I. src/testextension.c' % (workdir,))
    else:
        run('cd %s ; gcc -fPIC -shared -o testextension.sqlext -Isqlite3 -I. src/testextension.c' % (workdir,))

def buildapsw(outputfile, pybin, workdir):
    run("cd %s ; %s setup.py build >>%s 2>&1" % (workdir, pybin, outputfile))
    if pybin=="/usr/bin/python":
        run("cd %s ; cp build/*/apsw.so ." % (workdir,))
    else:
        run("cd %s ; %s setup.py install >>%s 2>&1" % (workdir, pybin, outputfile))


# Default versions we support
PYVERS=(
    '3.0rc3',
    '2.6',
    '2.5.2',
    '2.4.5',
    '2.3.7',
    'system',
    # '2.2.3',  - apsw not supported on 2.2 as it needs GILstate
    )

SQLITEVERS=(
    '3.6.5',
    '3.6.6'
   )

if __name__=='__main__':
    nprocs=0
    try:
        # try and work out how many processors there are - this works on linux
        for line in open("/proc/cpuinfo", "rt"):
            line=line.split()
            if line and line[0]=="processor":
                nprocs+=1
    except:
        pass
    # well there should be at least one!
    if nprocs==0:
        nprocs=1

    concurrency=nprocs*2

    parser=optparse.OptionParser()
    parser.add_option("--pyvers", dest="pyvers", help="Which Python versions to test against [%default]", default=",".join(PYVERS))
    parser.add_option("--sqlitevers", dest="sqlitevers", help="Which SQLite versions to test against [%default]", default=",".join(SQLITEVERS))
    parser.add_option("--cvs", dest="cvs", help="Also test current SQLite CVS version [%default]", default=False, action="store_true")
    parser.add_option("--ucs", dest="ucs", help="Unicode character widths to test in bytes [%default]", default="2,4")
    parser.add_option("--tasks", dest="concurrency", help="Number of simultaneous builds/tests to run [%default]", default=concurrency)

    options,args=parser.parse_args()

    if args:
        parser.error("Unexpect options "+str(options))

    pyvers=options.pyvers.split(",")
    sqlitevers=options.sqlitevers.split(",")
    if options.cvs:
        sqlitevers.append("cvs")
    ucstest=[int(x) for x in options.ucs.split(",")]
    concurrency=int(options.concurrency)
    sqlitevers=[x for x in sqlitevers if x]
    main(pyvers, ucstest, sqlitevers, concurrency)
