import logging
import attr
from arcana2.exceptions import ArcanaRepositoryError
from arcana2.exceptions import ArcanaUsageError
from ..enum import ClinicalTrial
from .xnat import Xnat


logger = logging.getLogger('arcana2')

COMMAND_INPUT_TYPES = {
    bool: 'bool',
    str: 'string',
    int: 'number',
    float: 'number'}


@attr.s
class XnatCS(Xnat):
    """
    A 'Repository' class for data stored within a XNAT repository and accessed
    via the XNAT container service.

    Parameters
    ----------
    root_dir : str (name_path)
        Path to local directory containing data
    """

    type = 'xnat_cs'
   



def make_command_json(image_name, analysis_cls, inputs, outputs,
                      parameters, desc, frequency=ClinicalTrial.session,
                      docker_index="https://index.docker.io/v1/"):

    if frequency != ClinicalTrial.session:
        raise NotImplementedError(
            "Support for frequencies other than '{}' haven't been "
            "implemented yet".format(frequency))
    try:
        analysis_name, version = image_name.split('/')[1].split(':')
    except (IndexError, ValueError):
        raise ArcanaUsageError(
            "The Docker organisation and tag needs to be provided as part "
            "of the image, e.g. australianimagingservice/dwiqa:0.1")

    cmd_inputs = []
    input_names = []
    for inpt in inputs:
        input_name = inpt if isinstance(inpt, str) else inpt[0]
        input_names.append(input_name)
        spec = analysis_cls.data_spec(input_name)
        desc = spec.desc if spec.desc else ""
        if spec.is_file_group:
            desc = ("Scan match: {} [SCAN_TYPE [ORDER [TAG=VALUE, ...]]]"
                    .format(desc))
        else:
            desc = "Field match: {} [FIELD_NAME]".format(desc)
        cmd_inputs.append({
            "name": input_name,
            "description": desc,
            "type": "string",
            "default-value": "",
            "required": True,
            "user-settable": True,
            "replacement-key": "#{}_INPUT#".format(input_name.upper())})

    for param in parameters:
        spec = analysis_cls.param_spec(param)
        desc = "Parameter: " + spec.desc
        if spec.choices:
            desc += " (choices: {})".format(','.join(spec.choices))

        cmd_inputs.append({
            "name": param,
            "description": desc,
            "type": COMMAND_INPUT_TYPES[spec.dtype],
            "default-value": (spec.default
                                if spec.default is not None else ""),
            "required": spec.default is None,
            "user-settable": True,
            "replacement-key": "#{}_PARAM#".format(param.upper())})

    cmd_inputs.append(
        {
            "name": "project-id",
            "description": "Project ID",
            "type": "string",
            "required": True,
            "user-settable": False,
            "replacement-key": "#PROJECT_ID#"
        })


    cmdline = (
        "arcana derive /input {cls} {name} {derivs} {inputs} {params}"
        " --scratch /work --repository xnat_cs #PROJECT_URI#"
        .format(
            cls='.'.join((analysis_cls.__module__, analysis_cls.__name__)),
            name=analysis_name,
            derivs=' '.join(outputs),
            inputs=' '.join('-i {} #{}_INPUT#'.format(i, i.upper())
                            for i in input_names),
            params=' '.join('-p {} #{}_PARAM#'.format(p, p.upper())
                            for p in parameters)))

    if frequency == ClinicalTrial.session:
        cmd_inputs.append(
            {
                "name": "session-id",
                "description": "",
                "type": "string",
                "required": True,
                "user-settable": False,
                "replacement-key": "#SESSION_ID#"
            })
        cmdline += "#SESSION_ID# --session_ids #SESSION_ID# "

    return {
        "name": analysis_name,
        "description": desc,
        "label": analysis_name,
        "version": version,
        "schema-version": "1.0",
        "image": image_name,
        "index": docker_index,
        "type": "docker",
        "command-line": cmdline,
        "override-entrypoint": True,
        "mounts": [
            {
                "name": "in",
                "writable": False,
                "name_path": "/input"
            },
            {
                "name": "output",
                "writable": True,
                "name_path": "/output"
            },
            {
                "name": "work",
                "writable": True,
                "name_path": "/work"
            }
        ],
        "ports": {},
        "inputs": cmd_inputs,
        "outputs": [
            {
                "name": "output",
                "description": "Derivatives",
                "required": True,
                "mount": "out",
                "name_path": None,
                "glob": None
            },
            {
                "name": "working",
                "description": "Working directory",
                "required": True,
                "mount": "work",
                "name_path": None,
                "glob": None
            }
        ],
        "xnat": [
            {
                "name": analysis_name,
                "description": desc,
                "contexts": ["xnat:imageSessionData"],
                "external-inputs": [
                    {
                        "name": "session",
                        "description": "Imaging session",
                        "type": "Session",
                        "selector": None,
                        "default-value": None,
                        "required": True,
                        "replacement-key": None,
                        "sensitive": None,
                        "provides-value-for-command-input": None,
                        "provides-files-for-command-mount": "in",
                        "via-setup-command": None,
                        "user-settable": None,
                        "load-children": True
                    }
                ],
                "derived-inputs": [
                    {
                        "name": "session-id",
                        "type": "string",
                        "required": True,
                        "load-children": True,
                        "derived-from-wrapper-input": "session",
                        "derived-from-xnat-object-property": "id",
                        "provides-value-for-command-input": "session-id"
                    },
                    {
                        "name": "subject",
                        "type": "Subject",
                        "required": True,
                        "user-settable": False,
                        "load-children": True,
                        "derived-from-wrapper-input": "session"
                    },
                    {
                        "name": "project-id",
                        "type": "string",
                        "required": True,
                        "load-children": True,
                        "derived-from-wrapper-input": "subject",
                        "derived-from-xnat-object-property": "id",
                        "provides-value-for-command-input": "subject-id"
                    }
                ],
                "output-handlers": [
                    {
                        "name": "output-resource",
                        "accepts-command-output": "output",
                        "via-wrapup-command": None,
                        "as-a-child-of": "session",
                        "type": "Resource",
                        "label": "Derivatives",
                        "format": None
                    },
                    {
                        "name": "working-resource",
                        "accepts-command-output": "working",
                        "via-wrapup-command": None,
                        "as-a-child-of": "session",
                        "type": "Resource",
                        "label": "Work",
                        "format": None
                    }
                ]
            }
        ]
    }