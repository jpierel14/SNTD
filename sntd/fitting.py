import warnings,sncosmo,os,sys,pyParz,pickle,subprocess,glob
import numpy as np
import matplotlib.pyplot as plt
from copy import deepcopy,copy
from scipy import stats
from astropy.table import Table
import nestle
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF
import scipy
import itertools
from sncosmo import nest_lc

from .util import *
from .curve_io import _sntd_deepcopy
from .models import *
from .ml import *

__all__=['fit_data']

__thetaSN__=['z','hostebv','screenebv','screenz','rise','fall','sigma','k','x1','c']
__thetaL__=['t0','amplitude','dt0','A','B','t1','psi','phi','s','x0']


_needs_bounds={'z'}

class newDict(dict):
    """
    This is just a dictionary replacement class that allows the use of a normal dictionary but with the ability
    to access via "dot" notation.
    """
    def __init__(self):
        super(newDict,self).__init__()

    # these three functions allow you to access the curveDict via "dot" notation
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__
    __getattr__ = dict.__getitem__

    def __getstate__(self):
        """
        A function necessary for pickling
        :return: self
        """
        return self

    def __setstate__(self, d):
        """
        A function necessary for pickling
        :param d: A value
        :return: self.__dict__
        """
        self.__dict__ = d



def fit_data(curves=None, snType='Ia',bands=None, models=None, params=None, bounds={}, ignore=None, constants=None,
             method='parallel',t0_guess=None,effect_names=[],effect_frames=[],batch_init=None,cut_time=None,
             dust=None,flip=False,microlensing=None,fitOrder=None,color_bands=None,min_points_per_band=3,
             fit_prior=None,par_or_batch='parallel',batch_partition=None,batch_script=None,nbatch_jobs=None,
             batch_python_path=None,wait_for_batch=False,guess_amplitude=True,test_micro=False,trial_fit=True,
             kernel='RBF',refImage='image_1',nMicroSamples=100,color_curve=None,warning_supress=True,
             verbose=True,**kwargs):

    """The main high-level fitting function.

    Parameters
    ----------
    curves: :class:`~sntd.curve_io.curveDict`
        The curveDict object containing the multiple images to fit.
    snType: str
        The supernova classification
    bands: :class:`~list` of :class:`~sncosmo.Bandpass` or :class:`~str`, or :class:`~sncosmo.Bandpass` or :class:`~str`
        The band(s) to be fit
    models: :class:`~list` of :class:`~sncosmo.Model` or str, or :class:`~sncosmo.Model` or :class:`~str`
        The model(s) to be used for fitting to the data
    params: :class:`~list` of :class:`~str`
        The parameters to be fit for the models inside of the parameter models
    bounds: :class:`dict`
        A dictionary with parameters in params as keys and a tuple of bounds as values
    ignore: :class:`~list` of :class:`~str`
        List of parameters to ignore
    constants: :class:`dict`
        Dictionary with parameters as keys and the constant value you want to set them to as values
    method: :class:`~str` or :class:`~list`
        Needs to be 'parallel', 'series', or 'color', or a list containting one or more of these
    t0_guess: :class:`dict`
        Dictionary with image names (i.e. 'image_1','image_2') as keys and a guess for time of peak as values
    effect_names: :class:`~list` of :class:`~str`
        List of effect names if model contains a :class:`~sncosmo.PropagationEffect`.
    effect_frames: :class:`~list` of :class:`~str`
        List of the frames (e.g. obs or rest) that correspond to the effects in effect_names
    dust: :class:`sncosmo.PropagationEffect`
        An sncosmo dust propagation effect to include in the model
    flip: bool
        If True, the time axis of the model is flipped

    microlensing: str
        If None microlensing is ignored, otherwise should be str (e.g. achromatic, chromatic)
    fitOrder: :class:`~list`
        The order you want to fit the images if using parallel method (default chooses by npoints/SNR)
    color_bands: :class:`~list`
        If using multiple methods (in batch mode), the subset of bands to use for color fitting.
    fit_prior: :class:`~sntd.curve_io.curveDict` or bool
        if implementing parallel method alongside others and fit_prior is True, will use output of parallel as prior
        for series/color. If SNTD curveDict object, used as prior for series or color.
    par_or_batch: str
        if providing a list of SNe, par means multiprocessing and batch means sbatch. Must supply other batch
        parameters if batch is chosen, so parallel is default.
    batch_partition: str
        The name of the partition for sbatch command
    batch_script: str
        filename for your own batch_script
    nbatch_jobs: int
        number of jobs (10 jobs for 100 light curves is 10 light curves per job)
    batch_python_path: str
        path to python you want to use for batch mode (if different from current)
    wait_for_batch: bool
        if false, submits job in the background. If true, waits for job to finish and returns output.
    guess_amplitude: bool
        If True, the amplitude parameter for the model is estimated, as well as its bounds
    kernel: str
        The kernel to use for microlensing GPR
    refImage: str
        The name of the image you want to be the reference image (i.e. image_1,image_2, etc.)
    nMicroSamples: int
        The number of pulls from the GPR posterior you want to use for microlensing uncertainty estimation
    color_curve: :class:`astropy.Table`
        A color curve to define the relationship between bands for parameterized light curve model.
    warning_supress: bool
        Turns on or off warnings
    verbose: bool
        Turns on/off the verbosity flag
    Returns
    -------
    fitted_curveDict: :class:`~sntd.curve_io.curveDict` or :class:`~list`
        The same curveDict that was passed to fit_data, but with new fits and time delay measurements included. List
        if list was provided.
    Examples
    --------
    >>> fitCurves=sntd.fit_data(myMISN,snType='Ia', models='salt2-extended',bands=['F110W','F125W'],
        params=['x0','x1','t0','c'],constants={'z':1.33},bounds={'t0':(-15,15),'x1':(-2,2),'c':(0,1)},
        method='parallel',microlensing=None)

    """

    #get together user arguments
    locs = locals()
    args = copy(locs)
    for k in kwargs.keys():
        args[k]=kwargs[k]

    if isinstance(curves,(list,tuple)):
        args['curves']=[]
        for i in range(len(curves)):
            temp=_sntd_deepcopy(curves[i])
            temp.nsn=i+1
            args['curves'].append(temp)
        args['parlist']=True
    else:
        args['curves']=_sntd_deepcopy(curves)
        args['parlist']=False

    if method !='color' or test_micro:
        args['bands'] = [bands] if bands is not None and not isinstance(bands,(tuple,list,np.ndarray)) else bands
        #sets the bands to user's if defined (set, so that they're unique), otherwise to all the bands that exist in curves

        args['bands'] = list(set(bands)) if bands is not None else None

        args['bands'] = list(curves.bands) if not isinstance(curves,(list,tuple,np.ndarray)) else list(curves[0].bands)
    #elif not test_micro and len(args['bands'])!=2:
    #    print('Must provide exactly 2 bands for color curve fitting.')
    #    sys.exit(1)

    models=[models] if models and not isinstance(models,(tuple,list)) else models
    if not models:
        mod,types=np.loadtxt(os.path.join(__dir__,'data','sncosmo','models.ref'),dtype='str',unpack=True)
        modDict={mod[i]:types[i] for i in range(len(mod))}
        if snType!='Ia':
            mods = [x[0] for x in sncosmo.models._SOURCES._loaders.keys() if x[0] in modDict.keys() and modDict[x[0]][:len(snType)]==snType]
        elif snType=='Ia':
            mods = [x[0] for x in sncosmo.models._SOURCES._loaders.keys() if 'salt2' in x[0]]
    else:
        mods=models
    mods=set(mods)
    args['mods']=mods
    if warning_supress:
        warnings.simplefilter('ignore')
    if test_micro and not args['parlist']:
        all_bands,color_bands=test_micro_func(args)
        args['color_bands']=color_bands
        args['bands']=all_bands
        args['curves'].micro_bands=all_bands
        args['curves'].micro_color_bands=color_bands



    if isinstance(method,(list,np.ndarray,tuple)):
        if len(method)==1:
            method=method[0]
        elif 'parallel' in method and fit_prior==True:
            method=np.append(['parallel'],[x for x in method if x!='parallel'])
        if args['parlist']:
            if par_or_batch=='parallel':
                print('Have not yet set up parallelized multi-fit processing')
                sys.exit(1)
            else:
                script_name,folder_name=run_sbatch(partition=batch_partition,sbatch_script=batch_script,
                                                   njobs=nbatch_jobs,python_path=batch_python_path)


                for i in range(len(args['curves'])):
                    args['curves'][i].constants={}
                    if constants is not None:
                        for c in constants:
                            if isinstance(constants[c],(list,tuple,np.ndarray)):

                                args['curves'][i].constants[c]=constants[c][i]
                            else:
                                args['curves'][i].constants[c]=constants[c]



                pickle.dump(args['curves'],open(os.path.join(folder_name,'sntd_data.pkl'),'wb'))

                with open(os.path.join(__dir__,'batch','run_sntd.py')) as f:
                    batch_py=f.read()
                batch_py=batch_py.replace('njobsreplace',str(nbatch_jobs))
                batch_py=batch_py.replace('nlcsreplace',str(len(args['curves'])))
                if batch_init is None:
                    batch_py=batch_py.replace('batchinitreplace','print("Nothing to initialize...")')
                else:
                    batch_py=batch_py.replace('batchinitreplace',batch_init)

                indent1=batch_py.find('fitCurves=')
                indent=batch_py.find('try:')+len('try:')+1


                sntd_command=''
                for i in range(len(method)):
                    fit_method=method[i]
                    sntd_command+='sntd.fit_data('
                    for par,val in locs.items():
                        if par =='curves':
                            if i==0:
                                sntd_command+='curves=all_dat[i],'
                            else:
                                sntd_command+='curves=fitCurves,'
                        elif par=='constants':
                            sntd_command+='constants=all_dat[i].constants,'
                        elif par=='batch_init':
                            sntd_command+='batch_init=None,'

                        elif par=='test_micro' and test_micro:
                            if i>0:
                                sntd_command+='test_micro=False,'
                            else:
                                sntd_command+='test_micro=True,'
                        elif par=='bands' and test_micro:
                            if i>0:
                                if fit_method!='color':
                                    sntd_command+='bands=fitCurves.micro_bands,'
                                else:
                                    sntd_command+='bands=fitCurves.micro_color_bands,'
                            else:
                                sntd_command+='bands=None,'
                        elif fit_method=='color' and par=='bands':
                            if color_bands is not None:
                                sntd_command+='bands='+str(color_bands)+','

                            #elif len(args['bands'])!=2:
                            #    print('Setting up color batch mode but more than 2 bands and color_bands not set,'+\
                            #          ')
                            #    sys.exit(1)
                            else:
                                sntd_command+='bands='+str(val)+','

                        elif par=='method':
                            sntd_command+='method="'+fit_method+'",'
                        elif par=='fit_prior' and fit_method!='parallel':
                            sntd_command+='fit_prior=fitCurves,'
                        elif isinstance(val,str):
                            sntd_command+=str(par)+'="'+str(val)+'",'
                        elif par=='kwargs':

                            for par2,val2 in val.items():
                                if isinstance(val,str):
                                    sntd_command+=str(par2)+'="'+str(val2)+'",'
                                else:
                                    sntd_command+=str(par2)+'='+str(val2)+','
                        else:
                            sntd_command+=str(par)+'='+str(val)+','

                    sntd_command=sntd_command[:-1]+')\n'
                    if i<len(method)-1:
                        sntd_command+=' '*(indent1-indent)+'fitCurves='

                batch_py=batch_py.replace('sntdcommandreplace',sntd_command)

                with open(os.path.join(folder_name,'run_sntd.py'),'w') as f:
                    f.write(batch_py)

                #os.system('sbatch %s'%(os.path.join(folder_name,script_name)))
                if wait_for_batch:

                    result=subprocess.call(['sbatch',os.path.join(os.path.abspath(folder_name),
                                                                  script_name)])
                    while True:
                        output=glob.glob(os.path.join(os.path.abspath(folder_name),'*fit*.pkl'))
                        printProgressBar(len(output),nbatch_jobs)
                        if len(output)==nbatch_jobs:
                            break

                    outfiles=glob.glob(os.path.join(os.path.abspath(folder_name),'*fit*.pkl'))
                    all_result=[]
                    for f in outfiles:
                        all_result.append(pickle.load(open(f,'rb')))

                    curves= list(np.reshape(all_result,(-1,1)).flatten())

                else:
                    result=subprocess.call(['sbatch', os.path.join(os.path.abspath(folder_name),
                                                                   script_name)])

                    print('Batch submitted successfully')
                    return



        else:
            initBounds=deepcopy(args['bounds'])
            if 'parallel' in method:
                print('Starting parallel method...')
                curves=_fitparallel(args)
                if args['fit_prior']==True:
                    args['fit_prior']=curves
                args['curves']=curves
                args['bounds']=copy(initBounds)
            if 'series' in method:
                print('Starting series method...')
                if 'td' not in args['bounds']:
                    print('td not in bounds for series method, choosing based on parallel bounds...')
                    args['bounds']['td']=args['bounds']['t0']
                if 'mu' not in args['bounds']:
                    print('mu not in bounds for series method, choosing defaults...')
                    args['bounds']['mu']=[0,10]

                curves=_fitseries(args)
                args['curves']=curves
                args['bounds']=copy(initBounds)
            if 'color' in method:
                print('Starting color method...')
                if 'td' not in args['bounds']:
                    print('td not in bounds for color method, choosing based on parallel bounds...')
                    args['bounds']['td']=args['bounds']['t0']
                #if len (args['bands'])>2:
                #    print('Did not specify 2 bands for color method, choosing first 2...')
                #    args['bands']=args['bands'][0:2]
                #elif len(args['bands'])<2:
                #    print('Must provide 2 bands for color method, skipping...')
                #    return(curves)

                curves=_fitColor(args)
    elif method not in ['parallel','series','color']:
            raise RuntimeError('Parameter "method" must be "parallel","series", or "color".')

    elif method=='parallel':
        if args['parlist']:
            if par_or_batch=='parallel':
                par_arg_vals=[]
                for i in range(len(args['curves'])):
                    temp_args={}
                    for par_key in ['snType','bounds','constants','t0_guess']:
                        if isinstance(args[par_key],(list,tuple,np.ndarray)):
                            temp_args[par_key]=args[par_key][i]
                    for par_key in ['bands','models','ignore','params']:
                        if isinstance(args[par_key],(list,tuple,np.ndarray)) and np.any([isinstance(x,(list,tuple,np.ndarray)) for x in args[par_key]]):
                            temp_args[par_key]=args[par_key][i]
                    par_arg_vals.append([args['curves'][i],temp_args])
                curves=pyParz.foreach(par_arg_vals,_fitparallel,[args])
            else:
                script_name,folder_name=run_sbatch(partition=batch_partition,sbatch_script=batch_script,
                                                   njobs=nbatch_jobs,python_path=batch_python_path)
                for i in range(len(args['curves'])):
                    args['curves'][i].constants={}
                    if constants is not None:
                        for c in constants:
                            if isinstance(constants[c],(list,tuple,np.ndarray)):

                                args['curves'][i].constants[c]=constants[c][i]
                            else:
                                args['curves'][i].constants[c]=constants[c]
                pickle.dump(args['curves'],open(os.path.join(folder_name,'sntd_data.pkl'),'wb'))

                with open(os.path.join(__dir__,'batch','run_sntd.py')) as f:
                    batch_py=f.read()
                batch_py=batch_py.replace('njobsreplace',str(nbatch_jobs))
                batch_py=batch_py.replace('nlcsreplace',str(len(args['curves'])))
                if batch_init is None:
                    batch_py=batch_py.replace('batchinitreplace','print("Nothing to initialize...")')
                else:
                    batch_py=batch_py.replace('batchinitreplace',batch_init)
                sntd_command='sntd.fit_data('
                for par,val in locs.items():

                    if par =='curves':
                        sntd_command+='curves=all_dat[i],'
                    elif par=='batch_init':
                        sntd_command+='batch_init=None,'
                    elif par=='constants':
                        sntd_command+='constants=all_dat[i].constants,'
                    elif par=='method':
                        sntd_command+='method="parallel",'
                    elif isinstance(val,str):
                        sntd_command+=str(par)+'="'+str(val)+'",'
                    elif par=='kwargs':

                        for par2,val2 in val.items():
                            if isinstance(val,str):
                                sntd_command+=str(par2)+'="'+str(val2)+'",'
                            else:
                                sntd_command+=str(par2)+'='+str(val2)+','

                    else:
                        sntd_command+=str(par)+'='+str(val)+','

                sntd_command=sntd_command[:-1]+')'

                batch_py=batch_py.replace('sntdcommandreplace',sntd_command)

                with open(os.path.join(folder_name,'run_sntd.py'),'w') as f:
                    f.write(batch_py)

                #os.system('sbatch %s'%(os.path.join(folder_name,script_name)))
                if wait_for_batch:
                    result=subprocess.call(['sbatch',os.path.join(os.path.abspath(folder_name),
                                                                  script_name)])
                    while True:
                        output=glob.glob(os.path.join(os.path.abspath(folder_name),'*fit*.pkl'))
                        printProgressBar(len(output),nbatch_jobs)
                        if len(output)==nbatch_jobs:
                            break


                    outfiles=glob.glob(os.path.join(os.path.abspath(folder_name),'*fit*.pkl'))
                    all_result=[]
                    for f in outfiles:
                        all_result.append(pickle.load(open(f,'rb')))

                    curves= list(np.reshape(all_result,(-1,1)).flatten())

                else:
                    result=subprocess.call(['sbatch', os.path.join(os.path.abspath(folder_name),
                                                                 script_name)])

                    print('Batch submitted successfully')
                    return



        else:
            curves=_fitparallel(args)
    elif method=='series':
        if args['parlist']:
            if par_or_batch=='parallel':
                par_arg_vals=[]
                for i in range(len(args['curves'])):
                    temp_args={}
                    for par_key in ['snType','bounds','constants','t0_guess']:
                        if isinstance(args[par_key],(list,tuple,np.ndarray)):
                            temp_args[par_key]=args[par_key][i]
                    for par_key in ['bands','models','ignore','params']:
                        if isinstance(args[par_key],(list,tuple,np.ndarray)) and np.any([isinstance(x,(list,tuple,np.ndarray)) for x in args[par_key]]):
                            temp_args[par_key]=args[par_key][i]
                    par_arg_vals.append([args['curves'][i],temp_args])
                curves=pyParz.foreach(par_arg_vals,_fitseries,[args])
            else:
                script_name,folder_name=run_sbatch(partition=batch_partition,sbatch_script=batch_script,
                                                   njobs=nbatch_jobs,python_path=batch_python_path)
                for i in range(len(args['curves'])):
                    args['curves'][i].constants={}
                    if constants is not None:
                        for c in constants:
                            if isinstance(constants[c],(list,tuple,np.ndarray)):

                                args['curves'][i].constants[c]=constants[c][i]
                            else:
                                args['curves'][i].constants[c]=constants[c]

                pickle.dump(args['curves'],open(os.path.join(folder_name,'sntd_data.pkl'),'wb'))

                with open(os.path.join(__dir__,'batch','run_sntd.py')) as f:
                    batch_py=f.read()
                batch_py=batch_py.replace('njobsreplace',str(nbatch_jobs))
                batch_py=batch_py.replace('nlcsreplace',str(len(args['curves'])))
                if batch_init is None:
                    batch_py=batch_py.replace('batchinitreplace','print("Nothing to initialize...")')
                else:
                    batch_py=batch_py.replace('batchinitreplace',batch_init)
                sntd_command='sntd.fit_data('
                for par,val in locs.items():
                    if par =='curves':
                        sntd_command+='curves=all_dat[i],'
                    elif par=='batch_init':
                        sntd_command+='batch_init=None,'
                    elif par=='constants':
                        sntd_command+='constants=all_dat[i].constants,'
                    elif par=='method':
                        sntd_command+='method="series",'
                    elif isinstance(val,str):
                        sntd_command+=str(par)+'="'+str(val)+'",'
                    elif par=='kwargs':

                        for par2,val2 in val.items():
                            if isinstance(val,str):
                                sntd_command+=str(par2)+'="'+str(val2)+'",'
                            else:
                                sntd_command+=str(par2)+'='+str(val2)+','
                    else:
                        sntd_command+=str(par)+'='+str(val)+','

                sntd_command=sntd_command[:-1]+')'

                batch_py=batch_py.replace('sntdcommandreplace',sntd_command)

                with open(os.path.join(folder_name,'run_sntd.py'),'w') as f:
                    f.write(batch_py)

                #os.system('sbatch %s'%(os.path.join(folder_name,script_name)))
                if wait_for_batch:
                    result=subprocess.call(['sbatch',os.path.join(os.path.abspath(folder_name),
                                                                  script_name)])
                    while True:
                        output=glob.glob(os.path.join(os.path.abspath(folder_name),'*fit*.pkl'))
                        printProgressBar(len(output),nbatch_jobs)
                        if len(output)==nbatch_jobs:
                            break


                    outfiles=glob.glob(os.path.join(os.path.abspath(folder_name),'*fit*.pkl'))
                    all_result=[]
                    for f in outfiles:
                        all_result.append(pickle.load(open(f,'rb')))

                    curves= list(np.reshape(all_result,(-1,1)).flatten())

                else:
                    result=subprocess.call(['sbatch', os.path.join(os.path.abspath(folder_name),
                                                                   script_name)])

                    print('Batch submitted successfully')
                    return
        else:
            curves=_fitseries(args)

    elif method=='color':
        if args['parlist']:
            if par_or_batch=='parallel':
                par_arg_vals=[]
                for i in range(len(args['curves'])):
                    temp_args={}
                    for par_key in ['snType','bounds','constants','t0_guess']:
                        if isinstance(args[par_key],(list,tuple,np.ndarray)):
                            temp_args[par_key]=args[par_key][i]
                    for par_key in ['bands','models','ignore','params']:
                        if isinstance(args[par_key],(list,tuple,np.ndarray)) and np.any([isinstance(x,(list,tuple,np.ndarray)) for x in args[par_key]]):
                            temp_args[par_key]=args[par_key][i]
                    par_arg_vals.append([args['curves'][i],temp_args])
                curves=pyParz.foreach(par_arg_vals,_fitColor,[args])
            else:
                script_name,folder_name=run_sbatch(partition=batch_partition,sbatch_script=batch_script,
                                                   njobs=nbatch_jobs,python_path=batch_python_path)
                for i in range(len(args['curves'])):
                    args['curves'][i].constants={}
                    if constants is not None:
                        for c in constants:
                            if isinstance(constants[c],(list,tuple,np.ndarray)):

                                args['curves'][i].constants[c]=constants[c][i]
                            else:
                                args['curves'][i].constants[c]=constants[c]

                pickle.dump(args['curves'],open(os.path.join(folder_name,'sntd_data.pkl'),'wb'))

                with open(os.path.join(__dir__,'batch','run_sntd.py')) as f:
                    batch_py=f.read()
                batch_py=batch_py.replace('njobsreplace',str(nbatch_jobs))
                batch_py=batch_py.replace('nlcsreplace',str(len(args['curves'])))
                if batch_init is None:
                    batch_py=batch_py.replace('batchinitreplace','print("Nothing to initialize...")')
                else:
                    batch_py=batch_py.replace('batchinitreplace',batch_init)
                sntd_command='sntd.fit_data('
                for par,val in locs.items():
                    if par =='curves':
                        sntd_command+='curves=all_dat[i],'
                    elif par=='batch_init':
                        sntd_command+='batch_init=None,'
                    elif par=='constants':
                        sntd_command+='constants=all_dat[i].constants,'
                    elif par=='method':
                        sntd_command+='method="color",'
                    elif isinstance(val,str):
                        sntd_command+=str(par)+'="'+str(val)+'",'
                    elif par=='kwargs':

                        for par2,val2 in val.items():
                            if isinstance(val,str):
                                sntd_command+=str(par2)+'="'+str(val2)+'",'
                            else:
                                sntd_command+=str(par2)+'='+str(val2)+','
                    else:
                        sntd_command+=str(par)+'='+str(val)+','

                sntd_command=sntd_command[:-1]+')'

                batch_py=batch_py.replace('sntdcommandreplace',sntd_command)

                with open(os.path.join(folder_name,'run_sntd.py'),'w') as f:
                    f.write(batch_py)

                #os.system('sbatch %s'%(os.path.join(folder_name,script_name)))
                if wait_for_batch:
                    result=subprocess.call(['sbatch',os.path.join(os.path.abspath(folder_name),
                                                                  script_name)])
                    while True:
                        output=glob.glob(os.path.join(os.path.abspath(folder_name),'*fit*.pkl'))
                        printProgressBar(len(output),nbatch_jobs)
                        if len(output)==nbatch_jobs:
                            break
                    outfiles=glob.glob(os.path.join(os.path.abspath(folder_name),'*fit*.pkl'))
                    all_result=[]
                    for f in outfiles:
                        all_result.append(pickle.load(open(f,'rb')))

                    curves= list(np.reshape(all_result,(-1,1)).flatten())

                else:
                    result=subprocess.call(['sbatch', os.path.join(os.path.abspath(folder_name),
                                                                   script_name)])

                    print('Batch submitted successfully')
                    return
        else:
            if args['color_bands'] is not None:
                args['bands']=args['color_bands']
            curves=_fitColor(args)


    return curves

def _fitColor(all_args):
    if isinstance(all_args,(list,tuple,np.ndarray)):
        curves,args=all_args
        if isinstance(args,list):
            args=args[0]
        if isinstance(curves,list):
            curves,single_par_vars=curves
            for key in single_par_vars:
                args[key]=single_par_vars[key]

        args['curves']=curves
        if args['verbose']:
            print('Fitting MISN number %i...'%curves.nsn)
    else:
        args=all_args
    args['bands']=list(args['bands'])
    if len(args['bands'])<2:
        raise RuntimeError("If you want to analyze color curves, you need two bands!")
    elif len(args['bands'])>2:

        all_SNR=[]
        for band in args['bands']:
            ims=[]
            for d in args['curves'].images.keys():
                inds=np.where(args['curves'].images[d].table['band']==band)[0]
                if len(inds)==0:
                    ims.append(0)
                else:
                    ims.append(np.sum(args['curves'].images[d].table['flux'][inds]/args['curves'].images[d].table['fluxerr'][inds])*\
                         np.sqrt(len(inds)))
            all_SNR.append(np.sum(ims))
        sorted=np.flip(np.argsort(all_SNR))
        args['bands']=np.array(args['bands'])[sorted]
        args['bands']=args['bands'][:2]

    if 't0' in args['params']:
        args['params'].remove('t0')

    imnums=[x[-1] for x in args['curves'].images.keys()]
    nimage=len(imnums)
    snParams=['t_%s'%i for i in imnums]
    all_vparam_names=np.append(args['params'],
                               snParams).flatten()

    ims=list(args['curves'].images.keys())

    for param in all_vparam_names:
        if param not in args['bounds'].keys():
            if param[:2]=='t_':
                if args['fit_prior'] is not None:

                    im=[x for x in ims if x[-1]==param[-1]][0]
                    args['bounds'][param]=3*np.array([args['fit_prior'].images[im].param_quantiles['t0'][0]- \
                                                      args['fit_prior'].images[im].param_quantiles['t0'][1],
                                                      args['fit_prior'].images[im].param_quantiles['t0'][2]- \
                                                      args['fit_prior'].images[im].param_quantiles['t0'][1]])
                else:
                    args['bounds'][param]=np.array(args['bounds']['td'])#+time_delays[im]

        elif args['fit_prior'] is not None:
            par_ref=args['fit_prior'].parallel.fitOrder[0]
            args['bounds'][param]=3*np.array([args['fit_prior'].images[par_ref].param_quantiles[param][0]- \
                                            args['fit_prior'].images[par_ref].param_quantiles[param][1],
                                            args['fit_prior'].images[par_ref].param_quantiles[param][2]- \
                                            args['fit_prior'].images[par_ref].param_quantiles[param][1]])+ \
                                  args['fit_prior'].images[par_ref].param_quantiles[param][1]

    if args['dust'] is not None:
        if isinstance(args['dust'],str):
            dust_dict={'CCM89Dust':sncosmo.CCM89Dust,'OD94Dust':sncosmo.OD94Dust,'F99Dust':sncosmo.F99Dust}
            dust=dust_dict[args['dust']]()
        else:
            dust=args['dust']
    else:
        dust=[]
    effect_names=args['effect_names']
    effect_frames=args['effect_frames']
    effects=[dust for i in range(len(effect_names))] if effect_names else []
    effect_names=effect_names if effect_names else []
    effect_frames=effect_frames if effect_frames else []
    if not isinstance(effect_names,(list,tuple)):
        effects=[effect_names]
    if not isinstance(effect_frames,(list,tuple)):
        effects=[effect_frames]

    finallogz=-np.inf
    for mod in np.array(args['models']).flatten():



        source=sncosmo.get_source(mod)
        tempMod = sncosmo.Model(source=source,effects=effects,effect_names=effect_names,effect_frames=effect_frames)
        tempMod.set(**args['constants'])


        if args['fit_prior'] is not None:
            par_ref=args['fit_prior'].parallel.fitOrder[0]
            temp_delays={k:args['fit_prior'].parallel.time_delays[k]-args['fit_prior'].parallel.time_delays[par_ref] \
                         for k in args['fit_prior'].parallel.fitOrder}
            args['curves'].color_table(args['bands'][0],args['bands'][1],time_delays=temp_delays)
            args['curves'].color.meta['reft0']=args['fit_prior'].images[par_ref].fits.model.get('t0')

        else:
            args['curves'].color_table(args['bands'][0],args['bands'][1],referenceImage=args['refImage'],
                                       static=False,model=tempMod)
            par_ref=args['refImage']


        if args['cut_time'] is not None:
            args['curves'].color.table=args['curves'].color.table[args['curves'].color.table['time']>=\
                                                                  args['cut_time'][0]*(1+tempMod.get('z'))+args['curves'].color.meta['reft0']]
            args['curves'].color.table=args['curves'].color.table[args['curves'].color.table['time']<=\
                                                                  args['cut_time'][1]*(1+tempMod.get('z'))+args['curves'].color.meta['reft0']]
        tempMod.set(t0=args['curves'].color.meta['reft0'])
        all_vparam_names=np.array([x for x in all_vparam_names if x!=tempMod.param_names[2]])
        params,res,model=nest_color_lc(args['curves'].color.table,tempMod,nimage,color=args['bands'],
                                            bounds=args['bounds'],
                                             vparam_names=all_vparam_names,ref=par_ref,
                                             minsnr=args.get('minsnr',5.),priors=args.get('priors',None),ppfs=args.get('ppfs',None),
                                             method=args.get('nest_method','single'),maxcall=args.get('maxcall',None),
                                             modelcov=args.get('modelcov',None),rstate=args.get('rstate',None),
                                             maxiter=args.get('maxiter',None),npoints=args.get('npoints',100))

        if finallogz<res.logz:
            finalres,finalmodel=res,model
            time_delays=args['curves'].color.meta['td']
            final_param_quantiles=params


    args['curves'].color.time_delays=dict([])
    args['curves'].color.time_delay_errors=dict([])
    args['curves'].color.t_peaks=dict([])
    args['curves'].color.param_quantiles={d:final_param_quantiles[finalres.vparam_names.index(d)] \
                                           for d in finalres.vparam_names}
    trefSamples=finalres.samples[:,finalres.vparam_names.index('t_'+args['refImage'][-1])]
    for k in args['curves'].images.keys():

        if k==args['refImage']:
            args['curves'].color.time_delays[k]=0
            args['curves'].color.time_delay_errors[k]=[0,0]
            if par_ref!=args['refImage']:
                args['curves'].color.t_peaks[k]=finalmodel.get('t0')+time_delays[args['refImage']]-\
                                            weighted_quantile(trefSamples,.5,finalres.weights)
            else:
                args['curves'].color.t_peaks[k]=finalmodel.get('t0')+time_delays[args['refImage']]+ \
                                                weighted_quantile(trefSamples,.5,finalres.weights)

        elif par_ref!=args['refImage']:
            ttempSamples=finalres.samples[:,finalres.vparam_names.index('t_'+k[-1])]
            t_quant=weighted_quantile(trefSamples-ttempSamples,[.16,.5,.84],finalres.weights)
            args['curves'].color.time_delays[k]=t_quant[1]+time_delays[k]-time_delays[args['refImage']]
            args['curves'].color.time_delay_errors[k]=np.array([t_quant[0]-t_quant[1],t_quant[2]-t_quant[1]])
            args['curves'].color.t_peaks[k]=finalmodel.get('t0')+time_delays[k]- \
                                            weighted_quantile(ttempSamples,.5,finalres.weights)

        else:
            ttempSamples=finalres.samples[:,finalres.vparam_names.index('t_'+k[-1])]
            t_quant=weighted_quantile(ttempSamples-trefSamples,[.16,.5,.84],finalres.weights)
            args['curves'].color.time_delays[k]=t_quant[1]+time_delays[k]
            args['curves'].color.time_delay_errors[k]=np.array([t_quant[0]-t_quant[1],t_quant[2]-t_quant[1]])
            args['curves'].color.t_peaks[k]=finalmodel.get('t0')+time_delays[k]+ \
                                            weighted_quantile(ttempSamples,.5,finalres.weights)




    finalmodel.set(t0=args['curves'].color.t_peaks[args['refImage']])

    args['curves'].color_table(args['bands'][0],args['bands'][1],time_delays=args['curves'].color.time_delays)
    args['curves'].color.meta['td']=time_delays
    args['curves'].color.refImage=args['refImage']
    args['curves'].color.priorImage=par_ref

    args['curves'].color.fits=newDict()
    args['curves'].color.fits['model']=finalmodel
    args['curves'].color.fits['res']=finalres

    return args['curves']

def nest_color_lc(data,model,nimage,color, vparam_names,bounds,ref='image_1',
                   minsnr=5., priors=None, ppfs=None, npoints=100, method='single',
                   maxiter=None, maxcall=None, modelcov=False, rstate=None,
                   verbose=False, warn=True,**kwargs):

    # experimental parameters
    tied = kwargs.get("tied", None)

    vparam_names=list(vparam_names)
    if ppfs is None:
        ppfs = {}
    if tied is None:
        tied = {}


    # Convert bounds/priors combinations into ppfs
    if bounds is not None:
        for key, val in bounds.items():
            if key in ppfs:
                continue  # ppfs take priority over bounds/priors
            a, b = val
            if priors is not None and key in priors:
                # solve ppf at discrete points and return interpolating
                # function
                x_samples = np.linspace(0., 1., 101)
                ppf_samples = sncosmo.utils.ppf(priors[key], x_samples, a, b)
                f = sncosmo.utils.Interp1D(0., 1., ppf_samples)
            else:
                f = sncosmo.utils.Interp1D(0., 1., np.array([a, b]))
            ppfs[key] = f

    # NOTE: It is important that iparam_names is in the same order
    # every time, otherwise results will not be reproducible, even
    # with same random seed.  This is because iparam_names[i] is
    # matched to u[i] below and u will be in a reproducible order,
    # so iparam_names must also be.


    iparam_names = [key for key in vparam_names if key in ppfs]



    ppflist = [ppfs[key] for key in iparam_names]
    npdim = len(iparam_names)  # length of u
    ndim = len(vparam_names)  # length of v

    # Check that all param_names either have a direct prior or are tied.
    for name in vparam_names:
        if name in iparam_names:
            continue
        if name in tied:
            continue
        raise ValueError("Must supply ppf or bounds or tied for parameter '{}'"
                         .format(name))

    def prior_transform(u):
        d = {}
        for i in range(npdim):
            d[iparam_names[i]] = ppflist[i](u[i])
        v = np.empty(ndim, dtype=np.float)
        for i in range(ndim):
            key = vparam_names[i]
            if key in d:
                v[i] = d[key]
            else:
                v[i] = tied[key](d)
        return v


    model_param_names=[x for x in vparam_names[:len(vparam_names)-nimage]]
    model_idx = np.array([vparam_names.index(name) for name in model_param_names])
    td_params=[x for x in vparam_names[len(vparam_names)-nimage:] if x[0]=='t']
    td_idx=np.array([vparam_names.index(name) for name in td_params])

    mindat=model.mintime()
    maxdat=model.maxtime()
    data=data[np.where(np.logical_and(data['time']>=mindat,data['time']<=maxdat))]
    im_indices=[np.where(data['image']==i)[0] for i in np.unique(data['image'])]
    def chisq_likelihood(parameters):
        model.set(**{model_param_names[k]:parameters[model_idx[k]] for k in range(len(model_idx))})
        all_data=deepcopy(data)

        for i in range(len(im_indices)):
            all_data['time'][im_indices[i]]-=parameters[td_idx[i]]

        model_observations = model.color(color[0],color[1],all_data['zpsys'][0],all_data['time'])


        if modelcov:
            all_cov=None
            cov = np.diag(all_data['%s-%s_err'%(color[0],color[1])]**2)
            for i in range(2):

                _, mcov = model.bandfluxcov(color[i],
                                            all_data['time'],
                                        zp=all_data['zp_%s'%color[i]],
                                        zpsys=all_data['zpsys'])


                if all_cov is None:
                    all_cov=copy(mcov)**2
                else:
                    all_cov+=copy(mcov)**2


            all_cov=np.sqrt(all_cov)

            cov = cov + all_cov
            invcov = np.linalg.pinv(cov)

            diff = all_data['%s-%s'%(color[0],color[1])]-model_observations
            chisq=np.dot(np.dot(diff, invcov), diff)

        else:
            chisq=np.sum((all_data['%s-%s'%(color[0],color[1])]-model_observations)**2/\
                         (all_data['%s-%s_err'%(color[0],color[1])]**2))
        return chisq

    def loglike(parameters):
        chisq=chisq_likelihood(parameters)
        if not np.isfinite(chisq):
            return -np.inf

        return(-.5*chisq)






    res = nestle.sample(loglike, prior_transform, ndim, npdim=npdim,
                        npoints=npoints, method=method, maxiter=maxiter,
                        maxcall=maxcall, rstate=rstate,
                        callback=(nestle.print_progress if verbose else None))

    res = sncosmo.utils.Result(niter=res.niter,
                               ncall=res.ncall,
                               logz=res.logz,
                               logzerr=res.logzerr,
                               h=res.h,
                               samples=res.samples,
                               weights=res.weights,
                               logvol=res.logvol,
                               logl=res.logl,
                               vparam_names=copy(vparam_names),
                               bounds=bounds)



    params=[weighted_quantile(res.samples[:,i],[.16,.5,.84],res.weights) for i in range(len(vparam_names))]

    model.set(**{model_param_names[k]:params[model_idx[k]][1] for k in range(len(model_idx))})

    return params,res,model


def _fitseries(all_args):
    if isinstance(all_args,(list,tuple,np.ndarray)):
        curves,args=all_args
        if isinstance(args,list):
            args=args[0]
        if isinstance(curves,list):
            curves,single_par_vars=curves
            for key in single_par_vars:
                args[key]=single_par_vars[key]

        args['curves']=curves
        if args['verbose']:
            print('Fitting MISN number %i...'%curves.nsn)
    else:
        args=all_args
    args['bands']=list(args['bands'])
    final_bands=[]
    for band in args['bands']:
        to_add=True
        for im in args['curves'].images.keys():
            if len(np.where(args['curves'].images[im].table['band']==band)[0])<args['min_points_per_band']:
                to_add=False
        if to_add:
            final_bands.append(band)
    args['bands']=np.array(final_bands)

    if 't0' in args['params']:
        args['params'].remove('t0')



    imnums=[x[-1] for x in args['curves'].images.keys()]
    nimage=len(imnums)
    snParams=[['t_%s'%i,'a_%s'%i] for i in imnums]
    all_vparam_names=np.append(args['params'],
                               snParams).flatten()

    ims=list(args['curves'].images.keys())


    for param in all_vparam_names:
        if param not in args['bounds'].keys():
            if param[:2]=='t_':
                if args['fit_prior'] is not None:
                    im=[x for x in ims if x[-1]==param[-1]][0]
                    args['bounds'][param]=3*np.array([args['fit_prior'].images[im].param_quantiles['t0'][0]- \
                                                      args['fit_prior'].images[im].param_quantiles['t0'][1],
                                                      args['fit_prior'].images[im].param_quantiles['t0'][2]- \
                                                      args['fit_prior'].images[im].param_quantiles['t0'][1]])
                else:
                    args['bounds'][param]=np.array(args['bounds']['td'])#+time_delays[im]
            elif param[:2]=='a_':
                if args['fit_prior'] is not None:

                    im=[x for x in ims if x[-1]==param[-1]][0]
                    amp=args['fit_prior'].images[im].fits.model.param_names[2]
                    args['bounds'][param]=(3*np.array([args['fit_prior'].images[im].param_quantiles[amp][0]-\
                                                      args['fit_prior'].images[im].param_quantiles[amp][1],
                                                      args['fit_prior'].images[im].param_quantiles[amp][2]- \
                                                      args['fit_prior'].images[im].param_quantiles[amp][1]])+ \
                                           args['fit_prior'].images[im].param_quantiles[amp][1])/ \
                                          args['fit_prior'].images[im].param_quantiles[amp][1]

                else:
                    args['bounds'][param]=np.array(args['bounds']['mu'])#*magnifications[im]
            elif args['fit_prior'] is not None:
                par_ref=args['fit_prior'].parallel.fitOrder[0]
                args['bounds'][param]=3*np.array([args['fit_prior'].images[par_ref].param_quantiles[param][0]- \
                                                args['fit_prior'].images[par_ref].param_quantiles[param][1],
                                                args['fit_prior'].images[par_ref].param_quantiles[param][2]- \
                                                args['fit_prior'].images[par_ref].param_quantiles[param][1]])+ \
                                      args['fit_prior'].images[par_ref].param_quantiles[param][1]

        elif args['fit_prior'] is not None:
            par_ref=args['fit_prior'].parallel.fitOrder[0]
            args['bounds'][param]=3*np.array([args['fit_prior'].images[par_ref].param_quantiles[param][0]- \
                                              args['fit_prior'].images[par_ref].param_quantiles[param][1],
                                              args['fit_prior'].images[par_ref].param_quantiles[param][2]- \
                                              args['fit_prior'].images[par_ref].param_quantiles[param][1]])+ \
                                  args['fit_prior'].images[par_ref].param_quantiles[param][1]
    finallogz=-np.inf
    if args['dust'] is not None:
        if isinstance(args['dust'],str):
            dust_dict={'CCM89Dust':sncosmo.CCM89Dust,'OD94Dust':sncosmo.OD94Dust,'F99Dust':sncosmo.F99Dust}
            dust=dust_dict[args['dust']]()
        else:
            dust=args['dust']
    else:
        dust=[]
    effect_names=args['effect_names']
    effect_frames=args['effect_frames']
    effects=[dust for i in range(len(effect_names))] if effect_names else []
    effect_names=effect_names if effect_names else []
    effect_frames=effect_frames if effect_frames else []
    if not isinstance(effect_names,(list,tuple)):
        effects=[effect_names]
    if not isinstance(effect_frames,(list,tuple)):
        effects=[effect_frames]


    for mod in np.array(args['models']).flatten():



        source=sncosmo.get_source(mod)
        tempMod = sncosmo.Model(source=source,effects=effects,effect_names=effect_names,effect_frames=effect_frames)
        tempMod.set(**args['constants'])
        all_vparam_names=np.array([x for x in all_vparam_names if x!=tempMod.param_names[2]])

        if not args['curves'].series.table:
            if args['fit_prior'] is not None:
                par_ref=args['fit_prior'].parallel.fitOrder[0]

                temp_delays={k:args['fit_prior'].parallel.time_delays[k]-args['fit_prior'].parallel.time_delays[par_ref]\
                             for k in args['fit_prior'].parallel.fitOrder}
                temp_mags={k:args['fit_prior'].parallel.magnifications[k]/args['fit_prior'].parallel.magnifications[par_ref] \
                             for k in args['fit_prior'].parallel.fitOrder}
                args['curves'].combine_curves(time_delays=temp_delays,
                    magnifications=temp_mags)
                args['curves'].series.meta['reft0']=args['fit_prior'].images[par_ref].fits.model.get('t0')
                args['curves'].series.meta['refamp']=\
                    args['fit_prior'].images[par_ref].fits.model.get(tempMod.param_names[2])
            else:
                par_ref=args['refImage']
                args['curves'].combine_curves(referenceImage=args['refImage'],static=False,model=tempMod)
            guess_amplitude=False
        else:
            par_ref=args['refImage']
            guess_amplitude=True
        if args['cut_time'] is not None:
            args['curves'].series.table=args['curves'].series.table[args['curves'].series.table['time']>= \
                                                                  args['cut_time'][0]*(1+tempMod.get('z'))+args['curves'].series.meta['reft0']]
            args['curves'].series.table=args['curves'].series.table[args['curves'].series.table['time']<= \
                                                                  args['cut_time'][1]*(1+tempMod.get('z'))+args['curves'].series.meta['reft0']]
        tempMod.set(t0=args['curves'].series.meta['reft0'])
        tempMod.parameters[2]=args['curves'].series.meta['refamp']

        params,res,model=nest_series_lc(args['curves'].series.table,tempMod,nimage,bounds=args['bounds'],
                                      vparam_names=all_vparam_names,ref=par_ref,
                                      guess_amplitude_bound=guess_amplitude,
                                      minsnr=args.get('minsnr',5.),priors=args.get('priors',None),ppfs=args.get('ppfs',None),
                                      method=args.get('nest_method','single'),maxcall=args.get('maxcall',None),
                                      modelcov=args.get('modelcov',None),rstate=args.get('rstate',None),
                                      maxiter=args.get('maxiter',None),npoints=args.get('npoints',100))
        if finallogz<res.logz:
            final_param_quantiles,finalres,finalmodel=params,res,model
            time_delays=args['curves'].series.meta['td']
            magnifications=args['curves'].series.meta['mu']

    args['curves'].series.param_quantiles={d:final_param_quantiles[finalres.vparam_names.index(d)] \
                                              for d in finalres.vparam_names}
    args['curves'].series.time_delays=dict([])
    args['curves'].series.magnifications=dict([])
    args['curves'].series.magnification_errors=dict([])
    args['curves'].series.time_delay_errors=dict([])

    args['curves'].series.t_peaks=dict([])
    args['curves'].series.a_peaks=dict([])

    trefSamples=finalres.samples[:,finalres.vparam_names.index('t_'+args['refImage'][-1])]
    arefSamples=finalres.samples[:,finalres.vparam_names.index('a_'+args['refImage'][-1])]
    for k in args['curves'].images.keys():

        if k==args['refImage']:
            args['curves'].series.time_delays[k]=0
            args['curves'].series.time_delay_errors[k]=[0,0]
            args['curves'].series.magnifications[k]=1
            args['curves'].series.magnification_errors[k]=[0,0]
            if par_ref!=args['refImage']:
                args['curves'].series.t_peaks[k]=finalmodel.get('t0')+time_delays[args['refImage']]- \
                                                weighted_quantile(trefSamples,.5,finalres.weights)
                args['curves'].series.a_peaks[k]=finalmodel.parameters[2]*magnifications[k]/ \
                                                 weighted_quantile(arefSamples,.5,finalres.weights)
            else:
                args['curves'].series.t_peaks[k]=finalmodel.get('t0')+time_delays[args['refImage']]+ \
                                                weighted_quantile(trefSamples,.5,finalres.weights)

                args['curves'].series.a_peaks[k]=finalmodel.parameters[2]*magnifications[k]* \
                                                 weighted_quantile(arefSamples,.5,finalres.weights)

        elif par_ref!=args['refImage']:
            ttempSamples=finalres.samples[:,finalres.vparam_names.index('t_'+k[-1])]
            atempSamples=finalres.samples[:,finalres.vparam_names.index('a_'+k[-1])]
            t_quant=weighted_quantile(trefSamples-ttempSamples,[.16,.5,.84],finalres.weights)
            a_quant=weighted_quantile(atempSamples/arefSamples,[.16,.5,.84],finalres.weights)
            args['curves'].series.time_delays[k]=t_quant[1]+time_delays[k]-time_delays[args['refImage']]
            args['curves'].series.time_delay_errors[k]=np.array([t_quant[0]-t_quant[1],t_quant[2]-t_quant[1]])
            args['curves'].series.t_peaks[k]=finalmodel.get('t0')+time_delays[k]- \
                                            weighted_quantile(ttempSamples,.5,finalres.weights)
            args['curves'].series.magnifications[k]=magnifications[k]*a_quant[1]/magnifications[args['refImage']]
            args['curves'].series.magnification_errors[k]= \
                magnifications[k]*np.array([a_quant[0]-a_quant[1],a_quant[2]-a_quant[1]])
            args['curves'].series.a_peaks[k]=finalmodel.parameters[2]*magnifications[k]/ \
                                             weighted_quantile(atempSamples,.5,finalres.weights)

        else:
            ttempSamples=finalres.samples[:,finalres.vparam_names.index('t_'+k[-1])]
            atempSamples=finalres.samples[:,finalres.vparam_names.index('a_'+k[-1])]
            t_quant=weighted_quantile(ttempSamples-trefSamples,[.16,.5,.84],finalres.weights)
            a_quant=weighted_quantile(atempSamples/arefSamples,[.16,.5,.84],finalres.weights)
            args['curves'].series.time_delays[k]=t_quant[1]+time_delays[k]
            args['curves'].series.time_delay_errors[k]=np.array([t_quant[0]-t_quant[1],t_quant[2]-t_quant[1]])
            args['curves'].series.magnifications[k]=magnifications[k]*a_quant[1]
            args['curves'].series.magnification_errors[k]= \
                magnifications[k]*np.array([a_quant[0]-a_quant[1],a_quant[2]-a_quant[1]])
            args['curves'].series.t_peaks[k]=finalmodel.get('t0')+time_delays[k]+ \
                                            weighted_quantile(ttempSamples,.5,finalres.weights)
            args['curves'].series.a_peaks[k]=finalmodel.parameters[2]*magnifications[k]* \
                                             weighted_quantile(atempSamples,.5,finalres.weights)



    args['curves'].combine_curves(time_delays=args['curves'].series.time_delays,magnifications=args['curves'].series.magnifications,referenceImage=args['refImage'])
    args['curves'].series.meta['td']=time_delays
    args['curves'].series.meta['mu']=magnifications

    finalmodel.set(t0=args['curves'].series.t_peaks[args['refImage']])
    finalmodel.parameters[2]=args['curves'].series.a_peaks[args['refImage']]

    args['curves'].series.refImage=args['refImage']
    args['curves'].series.priorImage=par_ref
    args['curves'].series.fits=newDict()
    args['curves'].series.fits['model']=finalmodel
    args['curves'].series.fits['res']=finalres


    if args['microlensing'] is not None:
        tempTable=deepcopy(args['curves'].series.table)
        micro,sigma,x_pred,y_pred,samples=fit_micro(args['curves'].series.fits.model,tempTable,
                                                    tempTable['zpsys'][0],args['nMicroSamples'],
                                                    micro_type=args['microlensing'],kernel=args['kernel'])

        temp_vparam_names=args['curves'].series.fits.res.vparam_names+[finalmodel.param_names[2]]+['t0']
        for im in args['curves'].images.keys():
            try:
                temp_vparam_names.remove('t_'+str(im[-1]))
                temp_vparam_names.remove('a_'+str(im[-1]))
            except:
                pass
        temp_bounds={p:args['curves'].series.param_quantiles[p][[0,2]] \
                     for p in args['curves'].series.fits.res.vparam_names}

        temp_bounds['t0']=args['bounds']['td']+args['curves'].series.t_peaks[args['refImage']]
        if args['par_or_batch']=='parallel':
            t0s=pyParz.foreach(samples.T,_micro_uncertainty,
                           [args['curves'].series.fits.model,np.array(tempTable),tempTable.colnames,
                            x_pred,temp_vparam_names,
                            temp_bounds,None,args.get('minsnr',0),args.get('maxcall',None)])
        else:
            return args['curves']
        mu,sigma=scipy.stats.norm.fit(t0s)

        args['curves'].series.param_quantiles['micro']=np.sqrt((args['curves'].series.fits.model.get('t0')-mu)**2 \
                                                                  +9*sigma**2)

    return args['curves']




def nest_series_lc(data,model,nimage,vparam_names,bounds,guess_amplitude_bound=False,ref='image_1',
                     minsnr=5., priors=None, ppfs=None, npoints=100, method='single',
                     maxiter=None, maxcall=None, modelcov=False, rstate=None,
                     verbose=False, warn=True,**kwargs):

    # experimental parameters
    tied = kwargs.get("tied", None)

    vparam_names=list(vparam_names)
    if ppfs is None:
        ppfs = {}
    if tied is None:
        tied = {}

    if guess_amplitude_bound:
        guess_t0,guess_amp=sncosmo.fitting.guess_t0_and_amplitude(sncosmo.photdata.photometric_data(data[data['image']==ref]),
                                                              model,minsnr)

    #print(guess_t0,guess_amp)
        model.set(t0=guess_t0)
        model.parameters[2]=guess_amp
    #bounds['x0']=(.1*guess_amp,10*guess_amp)

    # Convert bounds/priors combinations into ppfs
    if bounds is not None:
        for key, val in bounds.items():
            if key in ppfs:
                continue  # ppfs take priority over bounds/priors
            a, b = val
            if priors is not None and key in priors:
                # solve ppf at discrete points and return interpolating
                # function
                x_samples = np.linspace(0., 1., 101)
                ppf_samples = sncosmo.utils.ppf(priors[key], x_samples, a, b)
                f = sncosmo.utils.Interp1D(0., 1., ppf_samples)
            else:
                f = sncosmo.utils.Interp1D(0., 1., np.array([a, b]))
            ppfs[key] = f

    # NOTE: It is important that iparam_names is in the same order
    # every time, otherwise results will not be reproducible, even
    # with same random seed.  This is because iparam_names[i] is
    # matched to u[i] below and u will be in a reproducible order,
    # so iparam_names must also be.


    iparam_names = [key for key in vparam_names if key in ppfs]



    ppflist = [ppfs[key] for key in iparam_names]
    npdim = len(iparam_names)  # length of u
    ndim = len(vparam_names)  # length of v

    # Check that all param_names either have a direct prior or are tied.
    for name in vparam_names:
        if name in iparam_names:
            continue
        if name in tied:
            continue
        raise ValueError("Must supply ppf or bounds or tied for parameter '{}'"
                         .format(name))

    def prior_transform(u):
        d = {}
        for i in range(npdim):
            d[iparam_names[i]] = ppflist[i](u[i])
        v = np.empty(ndim, dtype=np.float)
        for i in range(ndim):
            key = vparam_names[i]
            if key in d:
                v[i] = d[key]
            else:
                v[i] = tied[key](d)
        return v


    model_param_names=[x for x in vparam_names[:len(vparam_names)-nimage*2]]
    model_idx = np.array([vparam_names.index(name) for name in model_param_names])
    td_params=[x for x in vparam_names[len(vparam_names)-nimage*2:] if x[0]=='t']
    td_idx=np.array([vparam_names.index(name) for name in td_params])
    amp_params=[x for x in vparam_names[len(vparam_names)-nimage*2:] if x[0]=='a']
    amp_idx=np.array([vparam_names.index(name) for name in amp_params])

    mindat=model.mintime()
    maxdat=model.maxtime()
    data=data[np.where(np.logical_and(data['time']>=mindat,data['time']<=maxdat))]
    im_indices=[np.where(data['image']==i)[0] for i in np.unique(data['image'])]

    def chisq_likelihood(parameters):
        model.set(**{model_param_names[k]:parameters[model_idx[k]] for k in range(len(model_idx))})
        all_data=deepcopy(data)

        for i in range(len(im_indices)):
            all_data['time'][im_indices[i]]-=parameters[td_idx[i]]
            all_data['flux'][im_indices[i]]/=parameters[amp_idx[i]]
        model_observations = model.bandflux(all_data['band'],all_data['time'],
                                            zp=all_data['zp'],zpsys=all_data['zpsys'])

        if modelcov:
            cov = np.diag(all_data['fluxerr']**2)
            _, mcov = model.bandfluxcov(all_data['band'], all_data['time'],
                                        zp=all_data['zp'], zpsys=all_data['zpsys'])

            cov = cov + mcov
            invcov = np.linalg.pinv(cov)

            diff = all_data['flux']-model_observations
            chisq=np.dot(np.dot(diff, invcov), diff)

        else:
            chisq=np.sum((all_data['flux']-model_observations)**2/(all_data['fluxerr']**2))
        return chisq

    def loglike(parameters):
        chisq=chisq_likelihood(parameters)
        if not np.isfinite(chisq):
            return -np.inf

        return(-.5*chisq)






    res = nestle.sample(loglike, prior_transform, ndim, npdim=npdim,
                        npoints=npoints, method=method, maxiter=maxiter,
                        maxcall=maxcall, rstate=rstate,
                        callback=(nestle.print_progress if verbose else None))

    res = sncosmo.utils.Result(niter=res.niter,
                               ncall=res.ncall,
                               logz=res.logz,
                               logzerr=res.logzerr,
                               h=res.h,
                               samples=res.samples,
                               weights=res.weights,
                               logvol=res.logvol,
                               logl=res.logl,
                               vparam_names=copy(vparam_names),
                               bounds=bounds)



    params=[weighted_quantile(res.samples[:,i],[.16,.5,.84],res.weights) for i in range(len(vparam_names))]
    model.set(**{model_param_names[k]:params[model_idx[k]][1] for k in range(len(model_idx))})



    return params,res,model



def _fitparallel(all_args):
    if isinstance(all_args,(list,tuple,np.ndarray)):
        curves,args=all_args
        if isinstance(args,list):
            args=args[0]
        if isinstance(curves,list):
            curves,single_par_vars=curves
            for key in single_par_vars:
                args[key]=single_par_vars[key]

        args['curves']=curves
        if args['verbose']:
            print('Fitting MISN number %i...'%curves.nsn)
    else:
        args=all_args

    if 't0' in args['bounds']:
        t0Bounds=copy(args['bounds']['t0'])
    final_bands=[]
    for band in list(args['bands']):
        to_add=True
        for im in args['curves'].images.keys():
            if len(np.where(args['curves'].images[im].table['band']==band)[0])<args['min_points_per_band']:
                to_add=False
        if to_add:
            final_bands.append(band)
    args['bands']=np.array(final_bands)
    
    for d in args['curves'].images.keys():
        for b in [x for x in np.unique(args['curves'].images[d].table['band']) if x not in args['bands']]:
            args['curves'].images[d].table=args['curves'].images[d].table[args['curves'].images[d].table['band']!=b]


    if 'amplitude' in args['bounds']:
        args['guess_amplitude']=False


    if args['fitOrder'] is None:
        all_SNR=[np.sum(args['curves'].images[d].table['flux']/args['curves'].images[d].table['fluxerr']) \
                    for d in np.sort(list(args['curves'].images.keys()))]
        sorted=np.flip(np.argsort(all_SNR))
        args['fitOrder']=np.sort(list(args['curves'].images.keys()))[sorted]

    args['curves'].parallel.fitOrder=args['fitOrder']

    if args['t0_guess'] is not None:
        if 't0' in args['bounds']:
            args['bounds']['t0']=(t0Bounds[0]+args['t0_guess'][d],t0Bounds[1]+args['t0_guess'][d])
            guess_t0=args['t0_guess']
        else:
            print('If you supply a t0 guess, you must also supply bounds.')
            sys.exit(1)

    initial_bounds=deepcopy(args['bounds'])
    finallogz=-np.inf
    if args['dust'] is not None:
        if isinstance(args['dust'],str):
            dust_dict={'CCM89Dust':sncosmo.CCM89Dust,'OD94Dust':sncosmo.OD94Dust,'F99Dust':sncosmo.F99Dust}
            dust=dust_dict[args['dust']]()
        else:
            dust=args['dust']
    else:
        dust=[]
    effect_names=args['effect_names']
    effect_frames=args['effect_frames']
    effects=[dust for i in range(len(effect_names))] if effect_names else []
    effect_names=effect_names if effect_names else []
    effect_frames=effect_frames if effect_frames else []
    if not isinstance(effect_names,(list,tuple)):
        effects=[effect_names]
    if not isinstance(effect_frames,(list,tuple)):
        effects=[effect_frames]


    for mod in np.array(args['models']).flatten():
        source=sncosmo.get_source(mod)
        tempMod = sncosmo.Model(source=source,effects=effects,effect_names=effect_names,effect_frames=effect_frames)
        tempMod.set(**args['constants'])
        guess_t0,guess_amp=sncosmo.fitting.guess_t0_and_amplitude( \
            sncosmo.photdata.photometric_data(args['curves'].images[args['fitOrder'][0]].table),
            tempMod,args.get('minsnr',5.))
        if 't0' in args['bounds'] and args['t0_guess'] is None:

            args['bounds']['t0']=np.array(args['bounds']['t0'])+guess_t0
        if args['guess_amplitude']:
            if tempMod.param_names[2] in args['bounds']:
                args['bounds'][tempMod.param_names[2]]=np.array(args['bounds'][tempMod.param_names[2]])*\
                    guess_amp
            else:
                args['bounds'][tempMod.param_names[2]]=[.1*guess_amp,10*guess_amp]
        if args['cut_time'] is not None:
            args['curves'].images[args['fitOrder'][0]].table=args['curves'].images[args['fitOrder'][0]].table[args['curves'].images[args['fitOrder'][0]].table['time']>= \
                                                                    args['cut_time'][0]*(1+tempMod.get('z'))+guess_t0]
            args['curves'].images[args['fitOrder'][0]].table=args['curves'].images[args['fitOrder'][0]].table[args['curves'].images[args['fitOrder'][0]].table['time']<= \
                                                                    args['cut_time'][1]*(1+tempMod.get('z'))+guess_t0]
        if args['trial_fit']:
            res,fit=sncosmo.fit_lc(args['curves'].images[args['fitOrder'][0]].table,tempMod,args['params'],
                                    bounds=args['bounds'],minsnr=args.get('minsnr',5.0))

            args['bounds']={res.param_names[i]:np.array([-res.errors[res.param_names[i]],res.errors[res.param_names[i]]])*3+\
                                               res.parameters[i] for i in range(len(res.param_names)) if res.param_names[i] \
                                                in list(res.errors.keys())}
            args['bounds']['t0']=np.array(initial_bounds['t0'])+fit.get('t0')

        res,fit=sncosmo.nest_lc(args['curves'].images[args['fitOrder'][0]].table,tempMod,args['params'],
                                bounds=args['bounds'],
                              priors=args.get('priors',None), ppfs=args.get('ppfs',None),
                                minsnr=args.get('minsnr',5.0), method=args.get('nest_method','single'),
                              maxcall=args.get('maxcall',None), modelcov=args.get('modelcov',False),
                              rstate=args.get('rstate',None),guess_amplitude_bound=False,
                              zpsys=args['curves'].images[args['fitOrder'][0]].zpsys,
                              maxiter=args.get('maxiter',None),npoints=args.get('npoints',100))
        if finallogz<res.logz:
            first_res=[args['fitOrder'][0],copy(fit),copy(res)]


    first_params=[weighted_quantile(first_res[2].samples[:,i],[.16,.5,.84],first_res[2].weights)\
                  for i in range(len(first_res[2].vparam_names))]

    args['curves'].images[args['fitOrder'][0]].fits=newDict()
    args['curves'].images[args['fitOrder'][0]].fits['model']=first_res[1]
    args['curves'].images[args['fitOrder'][0]].fits['res']=first_res[2]




    t0ind=first_res[2].vparam_names.index('t0')
    ampind=first_res[2].vparam_names.index(first_res[1].param_names[2])

    args['curves'].images[args['fitOrder'][0]].param_quantiles={k:first_params[first_res[2].vparam_names.index(k)] for\
                                                                 k in first_res[2].vparam_names}
    for d in args['fitOrder'][1:]:
        args['curves'].images[d].fits=newDict()
        initial_bounds['t0']=t0Bounds
        params,args['curves'].images[d].fits['model'],args['curves'].images[d].fits['res']\
            =nest_parallel_lc(args['curves'].images[d].table,first_res[1],first_res[2],initial_bounds,
                            guess_amplitude_bound=True,priors=args.get('priors',None), ppfs=args.get('None'),
                         method=args.get('nest_method','single'),cut_time=args['cut_time'],
                         maxcall=args.get('maxcall',None), modelcov=args.get('modelcov',False),
                         rstate=args.get('rstate',None),
                         maxiter=args.get('maxiter',None),npoints=args.get('npoints',1000))


    sample_dict={args['fitOrder'][0]:[first_res[2].samples[:,t0ind],first_res[2].samples[:,ampind]]}
    for k in args['fitOrder'][1:]:
        sample_dict[k]=[args['curves'].images[k].fits['res'].samples[:,t0ind],
                        args['curves'].images[k].fits['res'].samples[:,ampind]]
        args['curves'].images[k].param_quantiles={d:params[args['curves'].images[k].fits['res'].vparam_names.index(d)] \
                                                  for d in args['curves'].images[k].fits['res'].vparam_names}
    trefSamples,arefSamples=sample_dict[args['refImage']]
    refWeights=args['curves'].images[args['refImage']].fits['res'].weights
    for k in args['curves'].images.keys():
        if k==args['refImage']:
            args['curves'].parallel.time_delays={k:0}
            args['curves'].parallel.magnifications={k:1}
            args['curves'].parallel.time_delay_errors={k:[0,0]}
            args['curves'].parallel.magnification_errors={k:[0,0]}
        else:
            ttempSamples,atempSamples=sample_dict[k]

            if len(ttempSamples)>len(trefSamples):
                inds=np.flip(np.argsort(args['curves'].images[k].fits['res'].weights)[len(ttempSamples)-len(trefSamples):])
                inds_ref=np.flip(np.argsort(refWeights))
            else:
                inds_ref=np.flip(np.argsort(refWeights)[len(trefSamples)-len(ttempSamples):])
                inds=np.flip(np.argsort(args['curves'].images[k].fits['res'].weights))

            t_quant=weighted_quantile(ttempSamples[inds]-trefSamples[inds_ref],[.16,.5,.84],refWeights[inds_ref]* \
                                      args['curves'].images[k].fits['res'].weights[inds])
            a_quant=weighted_quantile(atempSamples[inds]/arefSamples[inds_ref],[.16,.5,.84],refWeights[inds_ref]* \
                                      args['curves'].images[k].fits['res'].weights[inds])
            args['curves'].parallel.time_delays[k]=t_quant[1]
            args['curves'].parallel.magnifications[k]=a_quant[1]
            args['curves'].parallel.time_delay_errors[k]=np.array([t_quant[0]-t_quant[1],t_quant[2]-t_quant[1]])
            args['curves'].parallel.magnification_errors[k]= \
                np.array([a_quant[0]-a_quant[1],a_quant[2]-a_quant[1]])


    if args['microlensing'] is not None:
        for k in args['curves'].images.keys():
            tempTable=deepcopy(args['curves'].images[k].table)
            micro,sigma,x_pred,y_pred,samples=fit_micro(args['curves'].images[k].fits.model,tempTable,
                                                        args['curves'].images[k].zpsys,args['nMicroSamples'],
                                                        micro_type=args['microlensing'],kernel=args['kernel'])


            if args['par_or_batch']=='parallel':


                t0s=pyParz.foreach(samples.T,_micro_uncertainty,
                               [args['curves'].images[k].fits.model,np.array(tempTable),tempTable.colnames,
                                x_pred,args['curves'].images[k].fits.res.vparam_names,
                                {p:args['curves'].images[k].param_quantiles[p][[0,2]]\
                                 for p in args['curves'].images[k].fits.res.vparam_names if p != \
                                 args['curves'].images[k].fits.model.param_names[2]},None,
                                args.get('minsnr',0),args.get('maxcall',None)])
            else:
                return args['curves']
            mu,sigma=scipy.stats.norm.fit(t0s)
            args['curves'].images[k].param_quantiles['micro']=np.sqrt((args['curves'].images[k].fits.model.get('t0')-mu)**2\
                                                                      +9*sigma**2)


    return args['curves']

def nest_parallel_lc(data,model,prev_res,bounds,guess_amplitude_bound=False,cut_time=None,
                   minsnr=5., priors=None, ppfs=None, npoints=100, method='single',
                   maxiter=None, maxcall=None, modelcov=False, rstate=None,
                   verbose=False, warn=True,**kwargs):

    # experimental parameters
    tied = kwargs.get("tied", None)

    vparam_names=list(prev_res.vparam_names)
    if ppfs is None:
        ppfs = {}
    if tied is None:
        tied = {}

    model=copy(model)
    if guess_amplitude_bound:
        guess_t0,guess_amp=sncosmo.fitting.guess_t0_and_amplitude(sncosmo.photdata.photometric_data(data),
                                                                  model,minsnr)

        #print(guess_t0,guess_amp)
        model.set(t0=guess_t0)
        model.parameters[2]=guess_amp

        bounds[model.param_names[2]]=(0,10*guess_amp)
        bounds['t0']=np.array(bounds['t0'])+guess_t0
    if cut_time is not None and guess_amplitude_bound:
        data=data[data['time']>=cut_time[0]*(1+model.get('z'))+guess_t0]
        data=data[data['time']<=cut_time[1]*(1+model.get('z'))+guess_t0]
    # Convert bounds/priors combinations into ppfs
    if bounds is not None:
        for key, val in bounds.items():
            if key in ppfs:
                continue  # ppfs take priority over bounds/priors
            a, b = val
            if priors is not None and key in priors:
                # solve ppf at discrete points and return interpolating
                # function
                x_samples = np.linspace(0., 1., 101)
                ppf_samples = sncosmo.utils.ppf(priors[key], x_samples, a, b)
                f = sncosmo.utils.Interp1D(0., 1., ppf_samples)
            else:
                f = sncosmo.utils.Interp1D(0., 1., np.array([a, b]))
            ppfs[key] = f

    # NOTE: It is important that iparam_names is in the same order
    # every time, otherwise results will not be reproducible, even
    # with same random seed.  This is because iparam_names[i] is
    # matched to u[i] below and u will be in a reproducible order,
    # so iparam_names must also be.

    final_priors=[]
    for p in vparam_names:
        if p==model.param_names[2] or p=='t0':
            final_priors.append(lambda x:0)
            continue

        ind=prev_res.vparam_names.index(p)
        temp=posterior('temp',np.min(prev_res.samples[:,ind]),np.max(prev_res.samples[:,ind]))
        samples=np.linspace(np.min(prev_res.samples[:,ind]),
                            np.max(prev_res.samples[:,ind]),1000)
        final_priors.append(scipy.interpolate.interp1d(samples,
                                                       np.log(temp._pdf(samples,prev_res.samples[:,ind],
                                                                        prev_res.weights)),fill_value=-np.inf,
                                                       bounds_error=False))

    iparam_names = [key for key in vparam_names if key in ppfs]



    ppflist = [ppfs[key] for key in iparam_names]
    npdim = len(iparam_names)  # length of u
    ndim = len(vparam_names)  # length of v
    # Check that all param_names either have a direct prior or are tied.
    for name in vparam_names:
        if name in iparam_names:
            continue
        if name in tied:
            continue
        raise ValueError("Must supply ppf or bounds or tied for parameter '{}'"
                         .format(name))

    def prior_transform(u):
        d = {}
        for i in range(npdim):
            d[iparam_names[i]] = ppflist[i](u[i])
        v = np.empty(ndim, dtype=np.float)
        for i in range(ndim):
            key = vparam_names[i]
            if key in d:
                v[i] = d[key]
            else:
                v[i] = tied[key](d)
        return v



    def chisq_likelihood(parameters):



        model.set(**{vparam_names[k]:parameters[k] for k in range(len(vparam_names))})
        model_observations = model.bandflux(data['band'],data['time'],
                                            zp=data['zp'],zpsys=data['zpsys'])

        if modelcov:
            cov = np.diag(data['fluxerr']**2)
            _, mcov = model.bandfluxcov(data['band'], data['time'],
                                        zp=data['zp'], zpsys=data['zpsys'])

            cov = cov + mcov
            invcov = np.linalg.pinv(cov)

            diff = data['flux']-model_observations
            chisq=np.dot(np.dot(diff, invcov), diff)

        else:
            chisq=np.sum((data['flux']-model_observations)**2/(data['fluxerr']**2))
        return chisq

    def loglike(parameters):
        prior_val=0
        for i in range(len(parameters)):
            temp_prior=final_priors[i](parameters[i])
            if not np.isfinite(temp_prior):
                return -np.inf
            prior_val+=temp_prior

        chisq=chisq_likelihood(parameters)
        if not np.isfinite(chisq):
            return -np.inf

        return(prior_val-.5*chisq)






    res = nestle.sample(loglike, prior_transform, ndim, npdim=npdim,
                        npoints=npoints, method=method, maxiter=maxiter,
                        maxcall=maxcall, rstate=rstate,
                        callback=(nestle.print_progress if verbose else None))

    res = sncosmo.utils.Result(niter=res.niter,
                               ncall=res.ncall,
                               logz=res.logz,
                               logzerr=res.logzerr,
                               h=res.h,
                               samples=res.samples,
                               weights=res.weights,
                               logvol=res.logvol,
                               logl=res.logl,
                               vparam_names=copy(vparam_names),
                               bounds=bounds)



    params=[weighted_quantile(res.samples[:,i],[.16,.5,.84],res.weights) for i in range(len(vparam_names))]

    model.set(**{vparam_names[k]:params[k][1] for k in range(len(vparam_names))})


    return params,model,res



def _micro_uncertainty(args):
    sample,other=args
    nest_fit,data,colnames,x_pred,vparam_names,bounds,priors,minsnr,maxcall=other
    data=Table(data,names=colnames)

    temp_nest_mod=deepcopy(nest_fit)
    tempMicro=AchromaticMicrolensing(x_pred/(1+nest_fit.get('z')),sample,magformat='multiply')
    temp_nest_mod.add_effect(tempMicro,'microlensing','rest')
    tempRes,tempMod=nest_lc(data,temp_nest_mod,vparam_names=vparam_names,bounds=bounds,minsnr=minsnr,maxcall=maxcall,
                            guess_amplitude_bound=True,maxiter=None,npoints=200,priors=priors)

    return float(tempMod.get('t0'))

def fit_micro(fit,dat,zpsys,nsamples,micro_type='achromatic',kernel='RBF'):
    t0=fit.get('t0')
    fit.set(t0=t0)
    data=deepcopy(dat)

    data['time']-=t0

    data=data[data['time']<=40.]
    data=data[data['time']>=-15.]
    if len(data)==0:
        data=deepcopy(dat)

    achromatic=micro_type.lower()=='achromatic'
    if achromatic:
        allResid=[]
        allErr=[]
        allTime=[]
    else:
        allResid=dict([])
        allErr=dict([])
        allTime=dict([])
    for b in np.unique(data['band']):
        tempData=data[data['band']==b]
        tempData=tempData[tempData['flux']>.1]
        tempTime=tempData['time']
        mod=fit.bandflux(b,tempTime+t0,zpsys=zpsys,zp=tempData['zp'])

        residual=tempData['flux']/mod
        tempData=tempData[~np.isnan(residual)]
        residual=residual[~np.isnan(residual)]
        tempTime=tempTime[~np.isnan(residual)]
        if achromatic:
            allResid=np.append(allResid,residual)
            allErr=np.append(allErr,residual*tempData['fluxerr']/tempData['flux'])
            allTime=np.append(allTime,tempTime)
        else:
            allResid[b]=residual
            allErr[b]=residual*tempData['fluxerr']/tempData['flux']
            allTime[b]=tempTime
    if kernel=='RBF':
        kernel = RBF(10., (20., 50.))

    if achromatic:
        gp = GaussianProcessRegressor(kernel=kernel, alpha=allErr ** 2,
                                      n_restarts_optimizer=100)

        try:
            gp.fit(np.atleast_2d(allTime).T,allResid.ravel())
        except:
            temp=np.atleast_2d(allTime).T
            temp2=allResid.ravel()
            temp=temp[~np.isnan(temp2)]
            temp2=temp2[~np.isnan(temp2)]
            gp.fit(temp,temp2)



        X=np.atleast_2d(np.linspace(np.min(allTime), np.max(allTime), 1000)).T

        y_pred, sigma = gp.predict(X, return_std=True)
        samples=gp.sample_y(X,nsamples)


        if False:
            plt.close()
            fig=plt.figure()
            ax=fig.gca()
            for i in range(samples.shape[1]):
                if i==0:
                    ax.plot(X, samples[:,i],alpha=.1,label='Posterior Samples',color='b')
                else:
                    ax.plot(X, samples[:,i],alpha=.1,color='b')
            ax.errorbar(allTime.ravel(), allResid, allErr, fmt='r.', markersize=10, label=u'Observations')

            ax.plot(X, y_pred - 3 * sigma, '--g')
            ax.plot(X, y_pred + 3 * sigma, '--g',label='$3\sigma$ Bounds')
            ax.plot(X,y_pred,'k-.',label="GPR Prediction")

            ax.set_ylabel('Magnification ($\mu$)')
            ax.set_xlabel('Observer Frame Time (Days)')
            ax.plot(X,curves.images['image_2'].simMeta['microlensing_params'](X/(1+1.33))/np.median(curves.images['image_2'].simMeta['microlensing_params'](X/(1+1.33))),'k',label='True $\mu$-Lensing')
            ax.legend(fontsize=10)
            plt.show()
            #plt.savefig('microlensing_gpr.pdf',format='pdf',overwrite=True)
            plt.close()
            #sys.exit()


        tempX=X[:,0]
        tempX=np.append([fit._source._phase[0]*(1+fit.get('z'))],np.append(tempX,[fit._source._phase[-1]*(1+fit.get('z'))]))
        y_pred=np.append([1.],np.append(y_pred,[1.]))
        sigma=np.append([0.],np.append(sigma,[0.]))

        result=AchromaticMicrolensing(tempX/(1+fit.get('z')),y_pred,magformat='multiply')

        '''
        fig=plt.figure()
        ax=fig.gca()
        #plt.plot(X, resid, 'r:', label=u'$f(x) = x\,\sin(x)$')
        ax.errorbar(allTime.ravel(), allResid, allErr, fmt='r.', markersize=10, label=u'Observations')
        #for c in np.arange(0,1.01,.1):
        #    for d in np.arange(-np.max(sigma),np.max(sigma),np.max(sigma)/10):
        #        plt.plot(X, 1+(y_pred[1:-1]-1)*c+d, 'b-')#, label=u'Prediction')
        ax.plot(X, y_pred[1:-1], 'b-' ,label=u'Prediction')

        ax.fill(np.concatenate([X, X[::-1]]),
                 np.concatenate([y_pred[1:-1] - 1.9600 * sigma[1:-1],
                                 (y_pred[1:-1] + 1.9600 * sigma[1:-1])[::-1]]),
                 alpha=.5, fc='b', ec='None', label='95% confidence interval')
        ax.set_xlabel('$x$')
        ax.set_ylabel('$f(x)$')
        #plt.xlim(-10, 50)
        #plt.ylim(.8, 1.4)

        ax.legend(loc='upper left')
        #plt.show()
        #plt.show()
        #figures.append(ax)
        #plt.clf()
        plt.close()
        '''


    else:
        pass
        #TODO make chromatic microlensing a thing



    return result,sigma,X[:,0],y_pred[1:-1],samples


def param_fit(args,modName,fit=False):
    sources={'BazinSource':BazinSource}

    source=sources[modName](args['curve'].table,colorCurve=args['color_curve'])
    mod=sncosmo.Model(source)
    if args['constants']:
        mod.set(**args['constants'])
    if not fit:
        res=sncosmo.utils.Result()
        res.vparam_names=args['params']
    else:
        #res,mod=sncosmo.fit_lc(args['curve'].table,mod,args['params'], bounds=args['bounds'],guess_amplitude=True,guess_t0=True,maxcall=1)

        if 'amplitude' in args['bounds']:
            guess_amp_bound=False
        else:
            guess_amp_bound=True




        res,mod=nest_lc(args['curve'].table,mod,vparam_names=args['params'],bounds=args['bounds'],
                        guess_amplitude_bound=guess_amp_bound,maxiter=1000,npoints=200)
    return({'res':res,'model':mod})


def test_micro_func(args):
    if len(args['bands'])<=2:
        return args['bands'],args['bands']
    res_dict={}
    original_args=copy(args)
    combos=[]
    for r in range(len(args['bands'])-1):
        temp=[x for x in itertools.combinations(original_args['bands'],r)]
        for t in temp:
            combos.append(t)
    for bands in itertools.combinations(args['bands'],2):
        good=True
        for b in bands:
            if not np.all([len(np.where(original_args['curves'].images[im].table['band']==b)[0])>=3 for im in original_args['curves'].images.keys()]):
                good=False
        if not good:
            continue
        temp_args=copy(original_args)

        temp_args['bands']=[x for x in bands]
        temp_args['npoints']=200
        temp_args['fit_prior']=None
        fitCurves=_fitColor(temp_args)
        if np.all([np.isfinite(fitCurves.color.time_delays[x]) for x in fitCurves.images.keys()]):
            res_dict[bands[0]+'-'+bands[1]]=copy(fitCurves.color.fits.res)

    if len(list(res_dict.keys()))==0:
        print('No good fitting.',args['bands'])
        return(args['bands'],args['bands'])

    # dev_dict={}
    # ind=res_dict[list(res_dict.keys())[0]].vparam_names.index('c')
    # for bs in combos:
    # 	dev_dict[','.join(list(bs))]=(np.average([weighted_quantile(res_dict[x].samples[:,ind],.5,res_dict[x].weights) \
    # 											  for x in res_dict.keys() if np.all([b not in x for b in bs])],weights= \
    # 												 [res_dict[x].logz for x in res_dict.keys() if np.all([b not in x for b in bs])]),
    # 				np.std([weighted_quantile(res_dict[x].samples[:,ind],.5,res_dict[x].weights) \
    # 		  for x in res_dict.keys() if np.all([b not in x for b in bs])]))
    # to_remove=None
    #
    # best_std=dev_dict[''][1]/np.sqrt(len(args['bands']))
    #
    # if len(args['bands'])>3:
    # 	for bands in dev_dict.keys():
    # 		if dev_dict[bands][1]!=0:#len(args['bands'])-len(bands.split(','))==2:
    # 			print(bands,dev_dict[bands][1])
    # 			if dev_dict[bands][1]/np.sqrt(len(args['bands'])-len(bands.split(',')))<best_std:
    # 				to_remove=bands.split(',')
    # 				best_std=dev_dict[bands][1]/np.sqrt(len(args['bands'])-len(to_remove))
    final_color_bands=None
    best_logz=-np.inf
    best_logzerr=0

    for bands in res_dict.keys():
        logz,logzerr=calc_ev(res_dict[bands],args['npoints'])
        if logz>best_logz:
            final_color_bands=bands
            best_logz=logz
            best_logzerr=logzerr

    final_all_bands=[]
    for bands in res_dict.keys():
        logz,logzerr=calc_ev(res_dict[bands],args['npoints'])
        if logz+3*logzerr>=best_logz-3*best_logzerr:
            final_all_bands=np.append(final_all_bands,bands.split('-'))



    return(np.unique(final_all_bands),np.array(final_color_bands.split('-')))

    #else:
    #	print([[x for x in args['bands'] if x not in to_remove]]*2)
    #	sys.exit()
    #	return [[x for x in args['bands'] if x not in to_remove]]*2

    # else:
    # 	best_bands=None
    # 	best_logz=-np.inf
    # 	for bands in res_dict.keys():
    #
    # 		if res_dict[bands].logz>best_logz:
    # 			best_bands=bands
    # 			best_logz=res_dict[bands].logz
    #
    # 	return [best_bands.split('-')]*2



def calc_ev(res,nlive):
    logZnestle = res.logz                         # value of logZ
    infogainnestle = res.h                        # value of the information gain in nats
    if not np.isfinite(infogainnestle):
        infogainnestle=.1*logZnestle
    logZerrnestle = np.sqrt(infogainnestle)#/nlive) # estimate of the statistcal uncertainty on logZ

    return logZnestle, logZerrnestle