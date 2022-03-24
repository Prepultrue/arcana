import logging
from abc import abstractmethod, ABCMeta
import inspect
from pathlib import Path
import attr
import typing as ty
import yaml
from arcana.core.utils import (
    get_config_file_path, list_subclasses, resolve_class, class_location,
    serialise, unserialise)
from arcana.exceptions import ArcanaUsageError, ArcanaNameError


logger = logging.getLogger('arcana')

@attr.s
class DataStore(metaclass=ABCMeta):
    # """
    # Abstract base class for all Repository systems, DaRIS, XNAT and
    # local file system. Sets out the interface that all Repository
    # classes should implement.
    # """

    _connection_depth = attr.ib(default=0, init=False, hash=False, repr=False,
                                eq=False)

    CONFIG_NAME = 'stores'

    @abstractmethod
    def find_nodes(self, dataset):
        """
        Find all data nodes for a dataset in the store and populate the
        Dataset object using its `add_node` method.

        Parameters
        ----------
        dataset : Dataset
            The dataset to populate with nodes
        """

    @abstractmethod
    def find_items(self, data_node):
        """
        Find all data items within a data node and populate the DataNode object
        with them using the `add_file_group` and `add_field` methods.
        
        Parameters
        ----------
        data_node : DataNode
            The data node to populate with items
        """        

    @abstractmethod
    def get_file_group_paths(self, file_group, cache_only=False):
        """
        Cache the file_group locally (if required) and return the locations
        of the cached primary file and side cars

        Parameters
        ----------
        file_group : FileGroup
            The file_group to cache locally
        cache_only : bool
            Whether to attempt to extract the file groups from the local cache
            (if applicable) and raise an error otherwise

        Returns
        -------
        path : str
            The file-system path to the cached file
        side_cars : Dict[str, str] or None
            The file-system paths to the cached side-cars if present

        Raises
        ------
        ArcanaCacheError
            If cache_only is set and there is a mismatch between the cached
            and remote versions
        """

    @abstractmethod
    def get_field_value(self, field):
        """
        Extract and return the value of the field from the store

        Parameters
        ----------
        field : Field
            The field to retrieve the value for

        Returns
        -------
        value : int | float | str | ty.List[int] | ty.List[float] | ty.List[str]
            The value of the Field
        """

    @abstractmethod
    def put_file_group_paths(self, file_group, path, **side_cars):
        """
        Inserts or updates the file_group into the store

        Parameters
        ----------
        file_group : FileGroup
            The file_group to insert into the store
        path : Path
            The file-system path to the primary file
        **side_cars
            Paths for additional files in the file group (e.g. header/side-cars)
        """

    @abstractmethod
    def put_field_value(self, field, value):
        """
        Inserts or updates the fields into the store

        Parameters
        ----------
        field : Field
            The field to insert into the store
        """
        
    @abstractmethod
    def save_dataset_definition(self,
                                dataset_id: str,
                                definition: ty.Dict[str, ty.Any],
                                name: str):
        """Save definition of dataset within the store

        Parameters
        ----------
        dataset_id: str
            The ID/path of the dataset within the store
        definition: dict[str, Any]
            A dictionary containing the serialised Dataset to be saved. The
            dictionary is in a format ready to be dumped to file as JSON or
            YAML.
        name: str
            Name for the dataset definition to distinguish it from other
            definitions for the same directory/project"""

    @abstractmethod
    def load_dataset_definition(self, dataset_id: str, name: str) -> ty.Dict[str, ty.Any]:
        """Load definition of a dataset saved within the store

        Parameters
        ----------
        dataset_id: str
            The ID (e.g. file-system path, XNAT project ID) of the project
        name: str
            Name for the dataset definition to distinguish it from other
            definitions for the same directory/project

        Returns
        -------
        definition: dict[str, Any]
            A serialised Dataset object that was saved in the data store
        """

    def get_checksums(self, file_group):
        """
        Override this method to return checksums for files that are stored
        with remote files (e.g. in XNAT). If no checksums are stored in the
        store then just leave this method to just access the file and
        recalculate them.

        Parameters
        ----------
        file_group : FileGroup
            The file_group to return the checksums for

        Returns
        -------
        checksums : dct[str, str]
            A dictionary with keys corresponding to the relative paths of all
            files in the file_group from the base path and values equal to the
            MD5 hex digest. The primary file in the file-set (i.e. the one that
            the path points to) should be specified by '.'.
        """
        return file_group.calculate_checksums()

    def connect(self):
        """
        If a connection session is required to the store manage it here
        """

    def disconnect(self):
        """
        If a connection session is required to the store manage it here
        """

    def save(self, name: str):
        """Saves the configuration of a DataStore in 'stores.yml' 

        Parameters
        ----------
        name
            The name under which to save the data store
        store : DataStore
            The DataStore to save
        """
        if name in self.singletons():
            raise ArcanaNameError(
                name, f"Name '{name}' clashes with built-in type of store")
        entries = self.load_saved_entries()
        # connect to store in case it is needed in the serialise method and to
        # test the connection in general before it is saved
        with self:  
            entries[name] = serialise(self)
        self.save_entries(entries)

    @classmethod
    def remove(cls, name: str):
        """Removes the entry saved under 'name' in the config file

        Parameters
        ----------
        name
            Name of the configuration to remove
        """
        entries = cls.load_saved_entries()
        del entries[name]
        cls.save_entries(entries)

    @classmethod
    def load(cls, name: str):
        """Loads a DataStore from that has been saved in the configuration file.
        If no entry is saved under that name, then it searches for DataStore
        sub-classes with aliases matching `name` and checks whether they can
        be initialised without any parameters.

        Parameters
        ----------
        name
            Name that the store was saved under

        Returns
        -------
        DataStore
            The data store retrieved from the stores.yml file

        Raises
        ------
        ArcanaNameError
            If the name is not found in the saved stores
        """
        entries = cls.load_saved_entries()
        try:
            entry = entries[name]
        except KeyError:
            try:
                return cls.singletons()[name]
            except KeyError:
                raise ArcanaNameError(
                    name,
                    f"No saved data store or built-in type matches '{name}'")
        else:
            store = resolve_class(entry.pop('type'))(**entry)
        return store


    def new_dataset(self, id, hierarchy=None, space=None, **kwargs):
        """
        Returns a dataset from the XNAT repository

        Parameters
        ----------
        id : str
            The ID (or file-system path) of the project (or directory) within
            the store
        space: DataSpace
            The data space of the dataset
        hierarchy: list[DataSpace or str]
            The hierarchy of the dataset
        space : EnumMeta
            The DataSpace enum that defines the frequencies (e.g.
            per-session, per-subject,...) present in the dataset.                       
        **kwargs:
            Keyword args passed on to the Dataset init method
        """
        if not hierarchy:
            try:
                hierarchy = self.DEFAULT_HIERARCHY
            except AttributeError as e:
                raise ArcanaUsageError(
                    "'hierarchy' kwarg must be specified for datasets in "
                    f"{type(self)} stores") from e
        if not space:
            try:
                space = self.DEFAULT_SPACE
            except AttributeError as e:
                raise ArcanaUsageError(
                    "'space' kwarg must be specified for datasets in "
                    f"{type(self)} stores") from e                
        from arcana.core.data.set import Dataset  # avoid circular imports it is imported here rather than at the top of the file
        dataset = Dataset(id, store=self, space=space, hierarchy=hierarchy,
                          **kwargs)           
        return dataset

    def load_dataset(self, id, name=None):
        from arcana.core.data.set import Dataset  # avoid circular imports it is imported here rather than at the top of the file
        if name is None:
            name = Dataset.DEFAULT_NAME
        serialised = self.load_dataset_definition(id, name)
        return unserialise(serialised, store=self)


    @classmethod
    def singletons(cls):
        """Returns stores in a dictionary indexed by their aliases, for which there only needs to be a single instance"""
        try:
            return cls._singletons
        except AttributeError:
            pass
        # If not saved in the configuration file search for sub-classes
        # whose alias matches `name` and can be initialised without params
        import arcana.data.stores
        cls._singletons = {}
        for store_cls in list_subclasses(arcana.data.stores, DataStore):
            try:
                cls._singletons[store_cls.get_alias()] = store_cls()
            except TypeError:
                pass
        return cls._singletons

    @classmethod
    def load_saved_entries(cls):
        fpath = get_config_file_path(cls.CONFIG_NAME)
        if fpath.exists():
            with open(fpath) as f:
                entries = yaml.load(f, Loader=yaml.Loader)
        else:
            entries = {}
        return entries

    @classmethod
    def save_entries(cls, entries):
        with open(get_config_file_path(cls.CONFIG_NAME), 'w') as f:
            yaml.dump(entries, f)

    def __enter__(self):
        # This allows the store to be used within nested contexts
        # but still only use one connection. This is useful for calling
        # methods that need connections, and therefore control their
        # own connection, in batches using the same connection by
        # placing the batch calls within an outer context.
        if self._connection_depth == 0:
            self.connect()
        self._connection_depth += 1
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self._connection_depth -= 1
        if self._connection_depth == 0:
            self.disconnect()

    @classmethod
    def get_alias(cls):
        try:
            alias = cls.alias
        except AttributeError:
            alias = cls.__name__.lower()
        return alias
