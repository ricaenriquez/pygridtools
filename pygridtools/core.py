from __future__ import division

import warnings
from copy import deepcopy

import numpy as np
from scipy import interpolate
import pandas

from pygridtools import misc
from pygridtools import iotools
from pygridtools import viz
from pygridtools import validate


def transform(nodes, fxn, *args, **kwargs):
    """
    Apply an arbitrary function to an array of node coordinates.

    Parameters
    ----------
    nodes : numpy.ndarray
        An N x M array of individual node coordinates (i.e., the
        x-coords or the y-coords only)
    fxn : callable
        The transformation to be applied to the whole ``nodes`` array
    args, kwargs
        Additional positional and keyword arguments that are passed to
        ``fxn``. The final call will be ``fxn(nodes, *args, **kwargs)``.

    Returns
    -------
    transformed : numpy.ndarray
        The transformed array.

    """

    return fxn(nodes, *args, **kwargs)


def split(nodes, index, axis=0):
    """
    Split a array of nodes into two separate, non-overlapping arrays.

    Parameters
    ----------
    nodes : numpy.ndarray
        An N x M array of individual node coordinates (i.e., the
        x-coords or the y-coords only)
    index : int
        The leading edge of where the split should occur.
    axis : int, optional
        The axis along which ``nodes`` will be split. Use `axis = 0`
        to split along rows and `axis = 1` for columns.

    Raises
    ------
    ValueError
        Trying to split ``nodes`` at the edge (i.e., resulting in the
        original array and an empty array) will raise an error.

    Returns
    -------
    n1, n2 : numpy.ndarrays
        The two non-overlapping sides of the original array.

    """

    if index + 1 >= nodes.shape[axis] or index == 0:
        raise ValueError("cannot split grid at or beyond its edges")

    if axis == 0:
        n1, n2 = nodes[:index, :], nodes[index:, :]
    elif axis == 1:
        n1, n2 = nodes[:, :index], nodes[:, index:]

    return n1, n2


def merge(nodes, other_nodes, how='vert', where='+', shift=0):
    """
    Merge two sets of nodes together.

    Parameters
    ----------
    nodes, other_nodes : numpy.ndarrays
        The sets of nodes that will be merged.
    how : string, optional (default = 'vert')
        The method through wich the arrays should be stacked.
        `'Vert'` is analogous to `np.vstack`. `'Horiz'` maps to
        `np.hstack`.
    where : string, optional (default = '+')
        The placement of the arrays relative to each other. Keeping
        in mind that the origin of an array's index is in the
        upper-left corner, `'+'` indicates that the second array
        will be placed at higher index relative to the first array.
        Essentially

        - if how == 'vert'

          - `'+'` -> `a` is above (higher index) `b`
          - `'-'` -> `a` is below (lower index) `b`

        - if how == 'horiz'

          - `'+'` -> `a` is to the left of `b`
          - `'-'` -> `a` is to the right of `b`

        See the examples and :func:~`pygridtools.misc.padded_stack` for
        more info.
    shift : int, optional (default = 0)
        The number of indices the second array should be shifted in
        axis other than the one being merged. In other words,
        vertically stacked arrays can be shifted horizontally,
        and horizontally stacked arrays can be shifted vertically.

    Returns
    -------
    merged : numpy.ndarrays
        The unified nodes coordinates.

    """

    return transform(nodes, misc.padded_stack, other_nodes, how=how,
                     where=where, shift=shift)


def _interp_between_vectors(vector1, vector2, n_nodes=1):
    if n_nodes < 1:
        raise ValueError("number of interpolated points must be at least 1")

    array = np.vstack([vector1, vector2]).T
    old_index = np.arange(2)
    interp = interpolate.interp1d(old_index, array, kind='linear')

    new_index = np.linspace(0, 1, num=n_nodes + 2)
    return interp(new_index).T


def insert(nodes, index, axis=0, n_nodes=1):
    """ Inserts new rows or columns between existing nodes.

    Parameters
    ----------
    nodes : numpy.ndarray
        The the array to be inserted.
    index : int
        The index within the array that will be inserted.
    axis : int
        Either 0 to insert rows or 1 to insert columns.
    n_nodes : int
        The number of new nodes to be inserted. In other words,
        ``n_nodes = 1`` implies that the given row to columns will
        be split in half. Similarly, ``n_nodes = 2`` will divide
        into thirds, ``n_nodes = 3`` implies quarters, and so on.

    Returns
    -------
    inserted : numpy.ndarray
        The modified node array.

    """

    if axis == 1:
        inserted = insert(nodes.T, index, axis=0, n_nodes=n_nodes).T
    else:
        top, bottom = split(nodes, index, axis=0)
        edge1, edge2 = top[-1, :], bottom[0, :]
        middle = _interp_between_vectors(edge1, edge2, n_nodes=n_nodes)
        inserted = np.vstack([top, middle[1:-1], bottom])

    return inserted


def extract(nodes, jstart=None, istart=None, jend=None, iend=None):
    """
    Extracts a subset of an array into new array.

    Parameters
    ----------
    jstart, jend : int, optional
        Start and end of the selection along the j-index
    istart, iend : int, optional
        Start and end of the selection along the i-index

    Returns
    -------
    subset : array
        The extracted subset of a copy of the original array.

    Notes
    -----
    Calling this without any [j|i][start|end] arguments effectively
    just makes a copy of the array.

    """
    return deepcopy(nodes[jstart:jend, istart:iend])


class ModelGrid(object):
    """
    Container for a curvilinear-orthogonal grid. Provides convenient
    access to masking, manipulation, and visualization methods.

    Although a good effort attempt is made to be consistent with the
    terminology, in general *node* and *vertex* are used
    interchangeably, with the former prefered over the latter.
    Similarly, *centroids* and *cells* can be interchangeable, although
    they are different. (Cell = the polygon created by 4 adjacent nodes
    and centroid = the centroid point of a cell).

    Parameters
    ----------
    nodes_x, nodes_y : numpy.ndarray
        M-by-N arrays of node (vertex) coordinates for the grid.

    """
    def __init__(self, nodes_x, nodes_y):
        if not np.all(nodes_x.shape == nodes_y.shape):
            raise ValueError('input arrays must have the same shape')

        self.nodes_x = np.asarray(nodes_x)
        self.nodes_y = np.asarray(nodes_y)
        self._template = None
        self._cell_mask = np.zeros(self.cell_shape, dtype=bool)

        self._domain = None
        self._extent = None
        self._islands = None

    @property
    def nodes_x(self):
        """Array of node x-coordinates. """
        return self._nodes_x

    @nodes_x.setter
    def nodes_x(self, value):
        self._nodes_x = value

    @property
    def nodes_y(self):
        """ Array of node y-coordinates. """
        return self._nodes_y

    @nodes_y.setter
    def nodes_y(self, value):
        """Array object of y-nodes"""
        self._nodes_y = value

    @property
    def cells_x(self):
        """Array of cell centroid x-coordinates"""
        xc = 0.25 * (
            self.xn[1:, 1:] + self.xn[1:, :-1] +
            self.xn[:-1, 1:] + self.xn[:-1, :-1]
        )
        return xc

    @property
    def cells_y(self):
        """Array of cell centroid y-coordinates"""
        yc = 0.25 * (
            self.yn[1:, 1:] + self.yn[1:, :-1] +
            self.yn[:-1, 1:] + self.yn[:-1, :-1]
        )
        return yc

    @property
    def shape(self):
        """ Shape of the nodes arrays """
        return self.nodes_x.shape

    @property
    def cell_shape(self):
        """ Shape of the cells arrays """
        return self.cells_x.shape

    @property
    def xn(self):
        """Shortcut to x-coords of nodes"""
        return self.nodes_x

    @property
    def yn(self):
        """Shortcut to y-coords of nodes"""
        return self.nodes_y

    @property
    def xc(self):
        """ Shortcut to x-coords of cells/centroids"""
        return self.cells_x

    @property
    def yc(self):
        """ Shortcut to y-coords of cells/centroids"""
        return self.cells_y

    @property
    def icells(self):
        """ Number of rows of cells"""
        return self.cell_shape[1]

    @property
    def jcells(self):
        """ Number of columns of cells"""
        return self.cell_shape[0]

    @property
    def inodes(self):
        """Number of rows of nodes"""
        return self.shape[1]

    @property
    def jnodes(self):
        """Number of columns of nodes"""
        return self.shape[0]

    @property
    def cell_mask(self):
        """ Boolean mask for the cells """
        return self._cell_mask

    @cell_mask.setter
    def cell_mask(self, value):
        self._cell_mask = value

    @property
    def template(self):
        """ Template shapefile (schema) for export """
        return self._template

    @template.setter
    def template(self, value):
        self._template = value

    @property
    def domain(self):
        """ The optional domain used to generate the raw grid """
        return self._domain

    @domain.setter
    def domain(self, value):
        self._domain = value

    @property
    def extent(self):
        """ The final extent of the model grid
        (everything outside is masked). """
        return self._extent

    @extent.setter
    def extent(self, value):
        self._extent = value

    @property
    def islands(self):
        """ Polygons used to make holes/gaps in the grid """
        return self._islands

    @islands.setter
    def islands(self, value):
        self._islands = value

    def transform(self, fxn, *args, **kwargs):
        """
        Apply an attribrary function to the grid nodes.

        Parameters
        ----------
        fxn : callable
            The function to be applied to the nodes. It should accept
            a node array as its first argument.

            .. note:
               The function is applied to each node array (x and y)
               individually.
        arg, kwargs : optional arguments and keyword arguments
            Additional values passed to ``fxn`` after the node array.

        Returns
        -------
        modelgrid
            A new :class:`~ModelGrid` is returned.

        """

        nodes_x = transform(self.nodes_x, fxn, *args, **kwargs)
        nodes_y = transform(self.nodes_y, fxn, *args, **kwargs)
        return ModelGrid(nodes_x, nodes_y)

    def copy(self):
        """
        Copies to nodes to a new model grid.

        Parameters
        ----------
        None

        Returns
        -------
        modelgrid
            A new :class:`~ModelGrid` is returned.

        """
        return self.transform(lambda x: x.copy())

    def transpose(self):
        """
        Transposes the node arrays of the model grid.

        Parameters
        ----------
        None

        Returns
        -------
        modelgrid
            A new :class:`~ModelGrid` is returned.

        """

        return self.transform(np.transpose)

    def fliplr(self):
        """
        Reverses the columns of the node arrays of the model grid.

        Parameters
        ----------
        None

        Returns
        -------
        modelgrid
            A new :class:`~ModelGrid` is returned.

        """

        return self.transform(np.fliplr)

    def flipud(self):
        """
        Reverses the rows of the node arrays of the model grid.

        Parameters
        ----------
        None

        Returns
        -------
        modelgrid
            A new :class:`~ModelGrid` is returned.

        """

        return self.transform(np.flipud)

    def split(self, index, axis=0):
        """
        Splits a model grid into two separate objects.

        Parameters
        ----------
        index : int
            The leading edge of where the split should occur.
        axis : int, optional
            The axis along which ``nodes`` will be split. Use `axis = 0`
            to split along rows and `axis = 1` for columns.

        Raises
        ------
        ValueError
            Trying to split at the edge (i.e., resulting in the
            original array and an empty array) will raise an error.

        Returns
        -------
        grid1, grid2 : ModelGrids
            The two non-overlapping sides of the grid.

        """

        x1, x2 = split(self.nodes_x, index, axis=axis)
        y1, y2 = split(self.nodes_y, index, axis=axis)
        return ModelGrid(x1, y1), ModelGrid(x2, y2)

    def insert(self, index, axis=0, n_nodes=1):
        """
        Inserts and linearly interpolates new nodes in an existing grid.

        Parameters
        ----------
        nodes : numpy.ndarray
            An N x M array of individual node coordinates (i.e., the
            x-coords or the y-coords only)
        index : int
            The leading edge of where the split should occur.
        axis : int, optional
            The axis along which ``nodes`` will be split. Use `axis = 0`
            to split along rows and `axis = 1` for columns.
        n_nodes : int, optional
            The number of *new* rows or columns to be inserted.

        Returns
        -------
        modelgrid
            A new :class:`~ModelGrid` is returned.

        """
        return self.transform(insert, index, axis=axis, n_nodes=n_nodes)

    def extract(self, jstart=0, istart=0, jend=-1, iend=-1):
        """
        Extracts a subset of an array into new grid.

        Parameters
        ----------
        jstart, jend : int, optional
            Start and end of the selection along the j-index
        istart, iend : int, optional
            Start and end of the selection along the i-index

        Returns
        -------
        subset : grid
            The extracted subset of a copy of the original grid.

        Notes
        -----
        Calling this without any [j|i][start|end] arguments effectively
        just makes a copy of the grid.

        """
        return self.transform(extract, jstart=jstart, istart=istart, jend=jend, iend=iend)

    def copy(self):
        return deepcopy(self)

    def merge(self, other, how='vert', where='+', shift=0):
        """
        Merge with another grid using pygridtools.misc.padded_stack.

        Parameters
        ----------
        other : ModelGrid
            The other ModelGrid object.
        how : optional string (default = 'vert')
            The method through wich the arrays should be stacked.
            `'Vert'` is analogous to `np.vstack`. `'Horiz'` maps to
            `np.hstack`.
        where : optional string (default = '+')
            The placement of the arrays relative to each other. Keeping
            in mind that the origin of an array's index is in the
            upper-left corner, `'+'` indicates that the second array
            will be placed at higher index relative to the first array.
            Essentially:

             - if how == 'vert'

               - `'+'` -> `a` is above (higher index) `b`
               - `'-'` -> `a` is below (lower index) `b`

             - if how == 'horiz'

               - `'+'` -> `a` is to the left of `b`
               - `'-'` -> `a` is to the right of `b`

            See the examples and pygridtools.misc.padded_stack for more
            info.
        shift : int (default = 0)
            The number of indices the second array should be shifted in
            axis other than the one being merged. In other words,
            vertically stacked arrays can be shifted horizontally,
            and horizontally stacked arrays can be shifted vertically.

        Returns
        -------
        modelgrid
            A new :class:`~ModelGrid` is returned.


        Examples
        --------
        >>> domain1 = pandas.DataFrame({
            'x': [2, 5, 5, 2],
            'y': [6, 6, 4, 4],
            'beta': [1, 1, 1, 1]
        })
        >>> domain2 = pandas.DataFrame({
            'x': [6, 11, 11, 5],
            'y': [5, 5, 3, 3],
            'beta': [1, 1, 1, 1]
        })
        >>> grid1 = pgt.makeGrid(domain=domain1, nx=6, ny=5, rawgrid=False)
        >>> grid2 = pgt.makeGrid(domain=domain2, nx=8, ny=7, rawgrid=False)
        >>> merged = grid1.merge(grid2, how='horiz')
        >>> # update the cell mask to include new NA points:
        >>> grid1.cell_mask = np.ma.masked_invalid(grid1.xc).mask

        See Also
        --------
        pygridtools.padded_stack

        """

        nodes_x = merge(self.nodes_x, other.nodes_x, how=how,
                        where=where, shift=shift)
        nodes_y = merge(self.nodes_y, other.nodes_y, how=how,
                        where=where, shift=shift)
        merged = ModelGrid(nodes_x, nodes_y).update_cell_mask()
        return merged

    def update_cell_mask(self, mask=None):
        """
        Regenerate the cell mask based on either the NaN cells
        or a user-provided mask. This is usefull after splitting,
        merging, or anything other transformation.

        Parameters
        ----------
        mask : numpy.ndarray of bools, optional
            The custom make to apply. If ommited, the mask will be
            determined by the missing values in the cells arrays.

        masked : ModelGrid
            A new :class:`~ModelGrid` wit the final mask to be applied
            to the cells.

        """

        if mask is None:
            mask = np.ma.masked_invalid(self.xc).mask

        masked = self.copy()
        masked.cell_mask = mask
        return masked

    def mask_cells_with_polygon(self, polyverts, use_centroids=True,
                                min_nodes=3, inside=True,
                                use_existing=True, triangles=False):

        """ Create mask for the cells of the ModelGrid with a polygon.

        Parameters
        ----------
        polyverts : sequence of a polygon's vertices
            A sequence of x-y pairs for each vertex of the polygon.
        use_centroids : bool (default = True)
            When True, the cell centroid will be used to determine
            whether the cell is "inside" the polygon. If False, the
            nodes are used instead.
        min_nodes : int (default = 3)
            Only used when ``use_centroids`` is False. This is the
            minimum number of nodes inside the polygon required to mark
            the cell as "inside". Must be greater than 0, but no more
            than 4.
        inside : bool (default = True)
            Toggles masking of cells either *inside* (True) or *outside*
            (False) the polygon.
        triangles : bool
            Not yet implemented.
        use_existing : bool (default = True)
            When True, the newly computed mask is combined (via a
            bit-wise `or` operation) with the existing ``cell_mask``
            attribute of the MdoelGrid.

        Returns
        -------
        masked : ModelGrid
            A new :class:`~ModelGrid` wit the final mask to be applied
            to the cells.

        """

        if triangles:
            raise NotImplementedError("triangles are not yet implemented.")

        if use_centroids:
            cell_mask = misc.mask_with_polygon(self.xc, self.yc, polyverts, inside=inside)
        else:
            if min_nodes <= 0 or min_nodes > 4:
                raise ValueError("`min_nodes` must be greater than 0 and no more than 4.")

            _node_mask = misc.mask_with_polygon(self.xn, self.yn, polyverts, inside=inside).astype(int)
            cell_mask = (
                _node_mask[1:, 1:] + _node_mask[:-1, :-1] +
                _node_mask[:-1, 1:] + _node_mask[1:, :-1]
            ) >= min_nodes
            cell_mask = cell_mask.astype(bool)

        if use_existing:
            cell_mask = np.bitwise_or(self.cell_mask, cell_mask)

        return self.update_cell_mask(mask=cell_mask)

    def writeGEFDCControlFile(self, outputdir=None, filename='gefdc.inp',
                              bathyrows=0, title='test'):
        """
        Generates the GEFDC control (gefdc.inp) file for the EFDC grid
        preprocessor.

        Parameters
        ----------
        outputdir : str, optional
            The path to where the should be saved.
        filename : str, optional
            The name of the output file.
        bathyrows : int, optional
            The number of rows in the grid's bathymetry data file.
        title : str, optional
            The title of the grid as portrayed in ``filename``.

        Returns
        -------
        gefdc : str
            The text of the output file.

        """

        outfile = iotools._outputfile(outputdir, filename)

        gefdc = iotools._write_gefdc_control_file(
            outfile,
            title,
            self.inodes + 1,
            self.jnodes + 1,
            bathyrows
        )
        return gefdc

    def writeGEFDCCellFile(self, outputdir=None, filename='cell.inp',
                           triangles=False, maxcols=125):
        """
        Generates the cell definition/ASCII-art file for GEFDC.

        .. warning:
           This whole thing is probably pretty buggy.

        Parameters
        ----------
        outputdir : str, optional
            The path to where the should be saved.
        filename : str, optional
            The name of the output file.
        triangles : bool, optional
            Toggles the inclusion of triangular cells.

            .. warning:
               This is experimental and probably buggy if it has been
               implmented at all.

        maxcols : int, optional
            The maximum number of columns to write to each row. Cells
            beyond this number will be writted in separate section at
            the bottom of the file.

        Returns
        -------
        cells : str
            The text of the output file.

        """

        cells = misc.make_gefdc_cells(
            ~np.isnan(self.xn), self.cell_mask, triangles=triangles
        )
        outfile = iotools._outputfile(outputdir, filename)

        iotools._write_cellinp(cells, outputfile=outfile,
                               flip=True, maxcols=maxcols)
        return cells

    def writeGEFDCGridFile(self, outputdir=None, filename='grid.out'):
        """
        Writes to the nodes as coordinate pairs for GEFDC.

        Parameters
        ----------
        outputdir : str, optional
            The path to where the should be saved.
        filename : str, optional
            The name of the output file.

        Returns
        -------
        df : pandas.DataFrame
            The dataframe of node coordinate pairs.

        """

        outfile = iotools._outputfile(outputdir, filename)
        df = iotools._write_gridout_file(self.xn, self.yn, outfile)
        return df

    def writeGEFDCGridextFile(self, outputdir, filename='gridext.inp', shift=2):
        """
        Writes to the nodes and I/J cell index as to a file for GEFDC.

        Parameters
        ----------
        outputdir : str, optional
            The path to where the should be saved.
        filename : str, optional
            The name of the output file.
        shift : int, optional
            The shift that should be applied to the I/J index. The
            default value to 2 means that the first cell is at (2, 2)
            instead of (0, 0).

        Returns
        -------
        df : pandas.DataFrame
            The dataframe of coordinates and I/J index.

        """
        outfile = iotools._outputfile(outputdir, filename)
        df = self.to_dataframe().stack(level='i', dropna=True).reset_index()
        df['i'] += shift
        df['j'] += shift
        iotools._write_gridext_file(df, outfile)
        return df

    def plotCells(self, engine='mpl', ax=None,
                  usemask=True, cell_kws=None,
                  domain_kws=None, extent_kws=None,
                  showisland=True, island_kws=None):
        """
        Creates a figure of the cells, boundary, domain, and islands.

        Parameters
        ----------
        engine : str
            The plotting engine to be used. Right now, only `'mpl'` has
            been implemented. Interactive figures via `'bokeh'` are
            planned.
        ax : matplotlib.Axes, optional
            The axes onto which the data will be drawn. If not provided,
            a new one will be created. Applies only to the *mpl* engine.
        usemask : bool, optional
            Whether or not cells should have the ModelGrid's mask
            applied to them.
        cell_kws, domain_kws, extent_kws, island_kws : dict
            Dictionaries of plotting options for each element
            of the figure.

            .. note:
            ``cell_kws`` and ``island_kws`` are feed to
            :func:`~matplotlib.pyplot.Polygon`. All others are sent
            to :meth:`~ax.plot`.

        """

        if cell_kws is None:
            cell_kws = {}
        fig = viz.plotCells(self.xn, self.yn, engine=engine, ax=ax,
                            mask=self.cell_mask, **cell_kws)

        if domain_kws is not None:
            fig = viz.plotDomain(data=self.domain, engine=engine, ax=ax, **domain_kws)

        if extent_kws:
            fig = viz.plotBoundaries(extent=self.extent, engine=engine, ax=ax, **extent_kws)

        if island_kws:
            fig = viz.plotBoundaries(islands=self.islands, engine=engine, ax=ax, **island_kws)

        return fig

    def _get_x_y(self, which, usemask=False):
        if which.lower() == 'nodes':
            if usemask:
                raise ValueError("can only mask cells, not nodes")
            else:
                x, y = self.xn, self.yn

        elif which.lower() == 'cells':
            x, y = self.xc, self.yc
            if usemask:
                x = np.ma.masked_array(x, self.cell_mask)
                y = np.ma.masked_array(y, self.cell_mask)

        else:
            raise ValueError('`which` must be either "nodes" or "cells"')

        return x, y

    def to_dataframe(self, usemask=False, which='nodes'):
        """
        Converts a grid to a wide dataframe of coordinates.

        Parameters
        ----------
        usemask : bool, optional
            Toggles the ommission of masked values (as determined by
            :meth:`~cell_mask`.
        which : str, optional ('nodes')
            This can be "nodes" (default) or "cells". Specifies which
            coordinates should be used.

        Returns
        -------
        pandas.DataFrame

        """

        x, y = self._get_x_y(which, usemask=usemask)

        def make_cols(top_level):
            columns = pandas.MultiIndex.from_product(
                [[top_level], range(x.shape[1])],
                names=['coord', 'i']
            )
            return columns

        index = pandas.Index(range(x.shape[0]), name='j')
        easting_cols = make_cols('easting')
        northing_cols = make_cols('northing')

        easting = pandas.DataFrame(x, index=index, columns=easting_cols)
        northing = pandas.DataFrame(y, index=index, columns=northing_cols)
        return easting.join(northing)

    def to_coord_pairs(self, usemask=False, which='nodes'):
        """
        Converts a grid to a long array of coordinates pairs.

        Parameters
        ----------
        usemask : bool, optional
            Toggles the ommission of masked values (as determined by
            :meth:`~cell_mask`.
        which : str, optional ('nodes')
            This can be "nodes" (default) or "cells". Specifies which
            coordinates should be used.

        Returns
        -------
        numpy.ndarray

        """

        x, y = self._get_x_y(which, usemask=usemask)
        return np.array(list(zip(x.flatten(), y.flatten())))

    def to_shapefile(self, outputfile, usemask=True, which='cells',
                     river=None, reach=0, elev=None, template=None,
                     geom='Polygon', mode='w', triangles=False):
        """
        Converts a grid to a shapefile via the *fiona* package.

        Parameters
        ----------
        outputfile : str
            The name of the shapefile where the data will be saved.
        usemask : bool, optional
            Toggles the ommission of masked values (as determined by
            :meth:`~cell_mask`.
        which : str, optional
            This can be "nodes" (default) or "cells". Specifies which
            coordinates should be used.
        river : str, optional
            Identifier of the river.
        reach : int or str, optional
            Indetifier of the reach of ``river``.
        elev : numpy.ndarray, optional
            Bathymetry data to be assigned to each record in the
            shapefile.
        template : str, optional
            The shapefile schema template. If not provided, the
            ``template`` attribute of the ModelGrid object is used.
        geom : str, optional
            The type of geometry to use. If "Point", either the grid
            nodes or the centroids of the can be used (see the
            ``which`` parameter). However, if "Polygon" is specified,
            cells will be generated from the nodes, regardless of the
            value of ``which``.
        mode : str, optional
            The mode in which ``outputfile`` will be opened. Should be
            either 'w' (write) or 'a' (append).
        triangles : bool, optional
            Toggles the inclusion of triangular cells.

            .. warning:
               This is experimental and probably buggy if it has been
               implmented at all.

        Returns
        -------
        None

        """

        if template is None:
            template = self.template

        if geom.lower() == 'point':
            x, y = self._get_x_y(which, usemask=usemask)
            iotools.savePointShapefile(x, y, template, outputfile,
                                       mode=mode, river=river, reach=reach,
                                       elev=elev)

        elif geom.lower() in ('cell', 'cells', 'grid', 'polygon'):
            if usemask:
                mask = self.cell_mask.copy()
            else:
                mask = None
            x, y = self._get_x_y('nodes', usemask=False)
            iotools.saveGridShapefile(x, y, mask, template,
                                      outputfile, mode=mode, river=river,
                                      reach=reach, elev=elev,
                                      triangles=triangles)
            if which == 'cells':
                warnings.warn("polygons always constructed from nodes")
        else:
            raise ValueError("geom must be either 'Point' or 'Polygon'")

    @classmethod
    def from_dataframe(cls, df, xcol='easting', ycol='northing', ilevel='ii'):
        """
        Build a ModelGrid from a DataFrame of I/J indexes and x/y
        columns.

        Parameters
        ----------
        df : pandas.DataFrame
            Must have a MultiIndex of I/J cell index values.
        xcol, ycol : str, optional
            The names of the columns for the x and y coordinates.
        ilevel : str, optional
            The index level specifying the I-index of the grid.

        Returns
        -------
        ModelGrid

        """

        nodes_x = df[xcol].unstack(level=ilevel)
        nodes_y = df[ycol].unstack(level=ilevel)
        return cls(nodes_x, nodes_y)

    @classmethod
    def from_shapefile(cls, shapefile, icol='ii', jcol='jj'):
        """
        Build a ModelGrid from a shapefile of *nodes*.

        Parameters
        ----------
        outputfile : str
            The name of the shapefile of the grid *nodes*.
        icol, jcol : str, optional
            The names of the columns in the shapefile containing the
            I/J index of the nodes.

        Returns
        -------
        ModelGrid

        """

        df = iotools.readGridShapefile(shapefile, icol=icol, jcol=jcol)
        return cls.from_dataframes(df['easting'], df['northing'])

    @classmethod
    def from_Gridgen(cls, gridgen):
        """
        Build a ModelGrid from a :class:`~pygridgen.Gridgen` object.

        Parameters
        ----------
        gridgen : pygridgen.Gridgen

        Returns
        -------
        ModelGrid

        """
        return cls(gridgen.x, gridgen.y)


def makeGrid(ny, nx, domain, bathydata=None, verbose=False,
             rawgrid=True, **gparams):
    """
    Generate a :class:`~pygridgen.Gridgen` or :class:`~ModelGrid`
    from scratch. This can take a large number of parameters passed
    directly to the ``Gridgen`` constructor. See the
    `Other Parameters` section.

    Parameters
    ----------
    ny, nx : int
        The number of rows and columns that will make up the grid's
        *nodes*. Note the final grid *cells* will be (ny-1) by (nx-1).
    domain : optional pandas.DataFrame or None (default)
        Defines the boundary of the model area. Must be provided if
        `makegrid` = True. Required columns:

          - 'x' (easting)
          - 'y' (northing),
          - 'beta' (turning points, must sum to 1)

    bathydata : optional pandas.DataFrame or None (default)
        Point bathymetry/elevation data. Will be interpolated unto the
        grid if provided. If None, a default value of 0 will be used.
        Required columns:

          - 'x' (easting)
          - 'y' (northing),
          - 'z' (elevation)

    verbose : bool, optional
        Toggles on the printing of status updates.
    rawgrid : bool (default = True)
        When True, returns a pygridgen.Gridgen object. Otherwise, a
        pygridtools.ModelGrid object is returned.

    Other Parameters
    ----------------
    ul_idx : optional int (default = 0)
        The index of the what should be considered the upper left
        corner of the grid boundary in the `xbry`, `ybry`, and
        `beta` inputs. This is actually more arbitrary than it
        sounds. Put it some place convenient for you, and the
        algorthim will conceptually rotate the boundary to place
        this point in the upper left corner. Keep that in mind when
        specifying the shape of the grid.
    focus : optional pygridgen.Focus instance or None (default)
        A focus object to tighten/loosen the grid in certain
        sections.
    proj : option pyproj projection or None (default)
        A pyproj projection to be used to convert lat/lon
        coordinates to a projected (Cartesian) coordinate system
        (e.g., UTM, state plane).
    nnodes : optional int (default = 14)
        The number of nodes used in grid generation. This affects
        the precision and computation time. A rule of thumb is that
        this should be equal to or slightly larger than
        -log10(precision).
    precision : optional float (default = 1.0e-12)
        The precision with which the grid is generated. The default
        value is good for lat/lon coordinate (i.e., smaller
        magnitudes of boundary coordinates). You can relax this to
        e.g., 1e-3 when working in state plane or UTM grids and
        you'll typically get better performance.
    nppe : optional int (default = 3)
        The number of points per internal edge. Lower values will
        coarsen the image.
    newton : optional bool (default = True)
        Toggles the use of Gauss-Newton solver with Broyden update
        to determine the sigma values of the grid domains. If False
        simple iterations will be used instead.
    thin : optional bool (default = True)
        Toggle to True when the (some portion of) the grid is
        generally narrow in one dimension compared to another.
    checksimplepoly : optional bool (default = True)
        Toggles a check to confirm that the boundary inputs form a
        valid geometry.
    verbose : optional bool (default = True)
        Toggles the printing of console statements to track the
        progress of the grid generation.

    Returns
    -------
    grid : pygridgen.Gridgen or ModelGrid

    Notes
    -----
    If your boundary has a lot of points, this really can take quite
    some time. Setting verbose=True will help track the progress of the
    grid generattion.

    See Also
    --------
    pygridgen.Gridgen, pygridgen.csa, pygridtools.ModelGrid

    """

    try:
        import pygridgen
    except ImportError:  # pragma: no cover
        raise ImportError("`pygridgen` not installed. Cannot make grid.")

    if verbose:
        print('generating grid')

    grid = pygridgen.Gridgen(domain.x, domain.y, domain.beta, (ny, nx), **gparams)

    if verbose:
        print('interpolating bathymetry')

    newbathy = misc.interpolate_bathymetry(bathydata, grid.x_rho, grid.y_rho,
                                           xcol='x', ycol='y', zcol='z')
    if rawgrid:
        return grid
    else:
        return ModelGrid.from_Gridgen(grid)
