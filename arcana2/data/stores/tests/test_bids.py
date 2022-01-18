import json
from pathlib import Path
import nibabel as nb
import numpy.random
import shutil
import docker
from arcana2 import __version__
from arcana2.data.types import niftix
from arcana2.data.stores.bids import BidsDataset
from arcana2.data.stores.bids import BidsApp
from arcana2.core.utils import resolve_class


BIDS_VALIDATOR_DOCKER = 'bids/validator'

def test_bids_roundtrip(work_dir):

    path = work_dir / 'bids-dataset'
    name = 'bids-dataset'

    dataset = BidsDataset.create(path, name,
                                 subject_ids=[str(i) for i in range(1, 4)],
                                 session_ids=[str(i) for i in range(1, 3)])

    dataset.readme = 'A dummy readme\n' * 100
    dataset.authors = ['Dumm Y. Author',
                       'Another D. Author']
    dataset.add_generator_metadata(
        name='arcana', version=__version__,
        description='Dataset was created programmatically from scratch',
        code_url='http://arcana.readthedocs.io')

    dataset.save_metadata()

    dataset.add_sink('t1w', datatype=niftix, path='anat/T1w')

    dummy_nifti = work_dir / 't1w.nii'
    # dummy_nifti_gz = dummy_nifti + '.gz'
    dummy_json = work_dir / 't1w.json'

    N = 10 ** 6

    # Create a random Nifti file to satisfy BIDS parsers
    hdr = nb.Nifti1Header()
    hdr.set_data_shape((10, 10, 10))
    hdr.set_zooms((1., 1., 1.))  # set voxel size
    hdr.set_xyzt_units(2)  # millimeters
    hdr.set_qform(numpy.diag([1,2,3,1]))
    nb.save(nb.Nifti1Image(
        numpy.random.randint(0, 1, size=[10, 10, 10]), hdr.get_best_affine(),
        header=hdr), dummy_nifti)

    with open(dummy_json, 'w') as f:
        json.dump({'test': 'json-file'}, f)

    for node in dataset.nodes(frequency='session'):
        item = node['t1w']
        item.put(dummy_nifti, side_cars={'json': dummy_json})

    # Full dataset validation using dockerized validator
    dc = docker.from_env()
    dc.images.pull(BIDS_VALIDATOR_DOCKER)
    result = dc.containers.run(BIDS_VALIDATOR_DOCKER, '/data',
                               volumes=[f'{path}:/data:ro'],
                               remove=True, stderr=True).decode('utf-8')
    assert 'This dataset appears to be BIDS compatible' in result
    
    reloaded = BidsDataset.load(path)
    reloaded.add_sink('t1w', datatype=niftix, path='anat/T1w')

    assert dataset == reloaded


def test_run_bids_app(nifti_sample_dir: Path, work_dir: Path):

    kwargs = {}
    INPUTS = ['bold', 'dwi', '']

    task = BidsApp(
        image=BIDS_VALIDATOR_DOCKER,
        executable='mriqc',  # Extracted using `docker_image_executable(docker_image)`
        inputs=BIDS_INPUTS,
        outputs=BIDS_OUTPUTS)

    task_location = 'arcana2.tasks.tests.fixtures:concatenate'
    task = resolve_class(task_location)

    for inpt, dtype in cmd_spec['inputs']:
        esc_inpt = inpt
        kwargs[esc_inpt] = nifti_sample_dir / (esc_inpt  + dtype.ext)

    bids_dir = work_dir / 'bids'

    shutil.rmtree(bids_dir, ignore_errors=True)

    result = task(dataset=bids_dir,
                  virtualisation='docker')(plugin='serial', id='DEFAULT', **kwargs)

    assert (Path(result.output.mriqc) / 'sub-DEFAULT_T1w.html').exists()
