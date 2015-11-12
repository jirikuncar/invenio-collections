# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2011, 2012, 2013, 2014, 2015 CERN.
#
# Invenio is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# Invenio is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Invenio; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

"""Database models for collections."""

# General imports.
import re
from datetime import datetime
from operator import itemgetter
from warnings import warn

from flask import g, url_for
from invenio_formatter.registry import output_formats
# Create your models here.
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import validates
from sqlalchemy.orm.collections import attribute_mapped_collection
from sqlalchemy.schema import Index
from werkzeug.utils import cached_property

from invenio_base.globals import cfg
from invenio_base.i18n import _, gettext_set_language
from invenio_db import db


class Collection(db.Model):

    """Represent a Collection record."""

    def __repr__(self):
        """Return class representation."""
        return 'Collection <id: {0.id}, name: {0.name}, dbquery: {0.query}, ' \
               'nbrecs: {0.nbrecs}>'.format(self)

    def __unicode__(self):
        """Unicode."""
        suffix = ' ({0})'.format(_('default')) if self.id == 1 else ''
        return u"{0.id}. {0.name}{1}".format(self, suffix)

    def __str__(self):
        """Str."""
        # TODO it's compatible with python 3?
        return unicode(self).encode('utf-8')

    __tablename__ = 'collection'
    id = db.Column(db.MediumInteger(9, unsigned=True),
                   primary_key=True)
    name = db.Column(db.String(255), unique=True, index=True, nullable=False)
    dbquery = db.Column(
        db.Text().with_variant(db.Text(20), 'mysql'),
        nullable=True)

    @validates('name')
    def validate_name(self, key, name):
        """Validate name.

        Name should not contain '/'-character. Root collection's name should
        equal CFG_SITE_NAME. Non-root collections should not have name equal to
        CFG_SITE_NAME.
        """
        if '/' in name:
            raise ValueError("collection name shouldn't contain '/'-character")

        if not self.is_root and name == cfg['CFG_SITE_NAME']:
            raise ValueError(("only root collection can "
                              "be named equal to the site's name"))

        if self.is_root and name != cfg['CFG_SITE_NAME']:
            warn('root collection name should be equal to the site name')

        return name

    @property
    def is_root(self):
        """Check whether the collection is a root collection."""
        return self.id == 1

    _names = db.relationship(lambda: Collectionname,
                             backref='collection',
                             collection_class=attribute_mapped_collection(
                                 'ln_type'),
                             cascade="all, delete, delete-orphan")

    names = association_proxy(
        '_names', 'value',
        creator=lambda k, v: Collectionname(ln_type=k, value=v)
    )
    _boxes = db.relationship(lambda: Collectionboxname,
                             backref='collection',
                             collection_class=attribute_mapped_collection(
                                 'ln_type'),
                             cascade="all, delete, delete-orphan")

    boxes = association_proxy(
        '_boxes', 'value',
        creator=lambda k, v: Collectionboxname(ln_type=k, value=v)
    )

    _formatoptions = association_proxy('formats', 'format')

    # @cache.memoize(make_name=lambda fname: fname + '::' + g.ln)
    def formatoptions(self):
        """Return list of format options."""
        if len(self._formatoptions):
            return [dict(f) for f in self._formatoptions]
        else:
            return [{'code': u'hb',
                     'name': _("HTML %(format)s", format=_("brief")),
                     'content_type': u'text/html'}]

    formatoptions = property(formatoptions)

    _examples_example = association_proxy('_examples', 'example')

    @property
    # @cache.memoize(make_name=lambda fname: fname + '::' + g.ln)
    def examples(self):
        """Return list of example queries."""
        return list(self._examples_example)

    @property
    def name_ln(self):
        """Name ln."""
        from .cache import get_coll_i18nname
        return get_coll_i18nname(self.name,
                                 getattr(g, 'ln', cfg['CFG_SITE_LANG']))
        # Another possible implementation with cache memoize
        # @cache.memoize
        # try:
        #    return db.object_session(self).query(Collectionname).\
        #        with_parent(self).filter(db.and_(Collectionname.ln==g.ln,
        #            Collectionname.type=='ln')).first().value
        # except Exception:
        #    return self.name

    @property
    # @cache.memoize(make_name=lambda fname: fname + '::' + g.ln)
    def portalboxes_ln(self):
        """Get Portalboxes ln."""
        return db.object_session(self).query(CollectionPortalbox).\
            with_parent(self).\
            options(db.joinedload_all(CollectionPortalbox.portalbox)).\
            filter(CollectionPortalbox.ln == g.ln).\
            order_by(db.desc(CollectionPortalbox.score)).all()

    @property
    def most_specific_dad(self):
        """Most specific dad."""
        results = sorted(
            db.object_session(self).query(Collection).join(
                Collection.sons
            ).filter(CollectionCollection.id_son == self.id).all(),
            key=lambda c: c.nbrecs)
        return results[0] if len(results) else None

    @property
    # @cache.memoize(make_name=lambda fname: fname + '::' + g.ln)
    def is_restricted(self):
        """Return ``True`` if the collection is restricted."""
        from .cache import collection_restricted_p
        return collection_restricted_p(self.name)

    @property
    def type(self):
        """Return relation type."""
        p = re.compile("\d+:.*")
        if self.dbquery is not None and \
                p.match(self.dbquery.lower()):
            return 'r'
        else:
            return 'v'

    _collection_children = db.relationship(
        lambda: CollectionCollection,
        collection_class=ordering_list('score'),
        primaryjoin=lambda: Collection.id == CollectionCollection.id_dad,
        foreign_keys=lambda: CollectionCollection.id_dad,
        order_by=lambda: db.asc(CollectionCollection.score)
    )
    _collection_children_r = db.relationship(
        lambda: CollectionCollection,
        collection_class=ordering_list('score'),
        primaryjoin=lambda: db.and_(
            Collection.id == CollectionCollection.id_dad,
            CollectionCollection.type == 'r'),
        foreign_keys=lambda: CollectionCollection.id_dad,
        order_by=lambda: db.asc(CollectionCollection.score)
    )
    _collection_children_v = db.relationship(
        lambda: CollectionCollection,
        collection_class=ordering_list('score'),
        primaryjoin=lambda: db.and_(
            Collection.id == CollectionCollection.id_dad,
            CollectionCollection.type == 'v'),
        foreign_keys=lambda: CollectionCollection.id_dad,
        order_by=lambda: db.asc(CollectionCollection.score)
    )
    collection_parents = db.relationship(
        lambda: CollectionCollection,
        collection_class=ordering_list('score'),
        primaryjoin=lambda: Collection.id == CollectionCollection.id_son,
        foreign_keys=lambda: CollectionCollection.id_son,
        order_by=lambda: db.asc(CollectionCollection.score)
    )
    collection_children = association_proxy('_collection_children', 'son')
    collection_children_r = association_proxy(
        '_collection_children_r', 'son',
        creator=lambda son: CollectionCollection(id_son=son.id, type='r')
    )
    collection_children_v = association_proxy(
        '_collection_children_v', 'son',
        creator=lambda son: CollectionCollection(id_son=son.id, type='v')
    )

    @property
    def search_within(self):
        """Collect search within options."""
        return [('', _('any field'))]

    @property
    # @cache.memoize(make_name=lambda fname: fname + '::' + g.ln)
    def search_options(self):
        """Return search options."""
        return self._search_options

    @cached_property
    def ancestors(self):
        """Get list of parent collection ids."""
        output = set([self])
        for c in self.dads:
            output |= c.dad.ancestors
        return output

    @cached_property
    def ancestors_ids(self):
        """Get list of parent collection ids."""
        output = set([self.id])
        for c in self.dads:
            ancestors = c.dad.ancestors_ids
            if self.id in ancestors:
                raise
            output |= ancestors
        return output

    @cached_property
    def descendants_ids(self):
        """Get list of child collection ids."""
        output = set([self.id])
        for c in self.sons:
            descendants = c.son.descendants_ids
            if self.id in descendants:
                raise
            output |= descendants
        return output

    # Gets the list of localized names as an array
    collection_names = db.relationship(
        lambda: Collectionname,
        primaryjoin=lambda: Collection.id == Collectionname.id_collection,
        foreign_keys=lambda: Collectionname.id_collection
    )

    def translation(self, lang):
        """Get the translation according to the language code."""
        try:
            return db.object_session(self).query(Collectionname).\
                with_parent(self).filter(db.and_(
                    Collectionname.ln == lang,
                    Collectionname.type == 'ln'
                )).first().value
        except Exception:
            return ""

    @property
    def sort_methods(self):
        """Get sort methods for collection.

        If not sort methods are defined for a collection the root collections
        sort methods are retuned. If not methods are defined for the root
        collection, all possible sort methods are returned.

        Note: Noth sorting methods and ranking methods are now defined via
        the sorter.
        """
        return []

    def get_collectionbox_name(self, ln=None, box_type="r"):
        """Return collection-specific labelling subtrees.

        - 'Focus on': regular collection
        - 'Narrow by': virtual collection
        - 'Latest addition': boxes

        If translation for given language does not exist, use label
        for CFG_SITE_LANG. If no custom label is defined for
        CFG_SITE_LANG, return default label for the box.

        :param ln: the language of the label
        :param box_type: can be 'r' (=Narrow by), 'v' (=Focus on),
                         'l' (=Latest additions)
        """
        if ln is None:
            ln = g.ln
        collectionboxnamequery = db.object_session(self).query(
            Collectionboxname).with_parent(self)
        try:
            collectionboxname = collectionboxnamequery.filter(db.and_(
                Collectionboxname.ln == ln,
                Collectionboxname.type == box_type,
            )).one()
        except Exception:
            try:
                collectionboxname = collectionboxnamequery.filter(db.and_(
                    Collectionboxname.ln == ln,
                    Collectionboxname.type == box_type,
                )).one()
            except Exception:
                collectionboxname = None

        if collectionboxname is None:
            # load the right message language
            _ = gettext_set_language(ln)
            return _(Collectionboxname.TYPES.get(box_type, ''))
        else:
            return collectionboxname.value

    portal_boxes_ln = db.relationship(
        lambda: CollectionPortalbox,
        collection_class=ordering_list('score'),
        primaryjoin=lambda:
        Collection.id == CollectionPortalbox.id_collection,
        foreign_keys=lambda: CollectionPortalbox.id_collection,
        order_by=lambda: db.asc(CollectionPortalbox.score))

    def breadcrumbs(self, builder=None, ln=None):
        """Return breadcrumbs for collection."""
        ln = cfg.get('CFG_SITE_LANG') if ln is None else ln
        breadcrumbs = []
        # Get breadcrumbs for most specific dad if it exists.
        if self.most_specific_dad is not None:
            breadcrumbs = self.most_specific_dad.breadcrumbs(builder=builder,
                                                             ln=ln)

        if builder is not None:
            crumb = builder(self)
        else:
            crumb = dict(
                text=self.name_ln,
                url=url_for('invenio_collections.collection', name=self.name))

        breadcrumbs.append(crumb)
        return breadcrumbs


Index('ix_collection_dbquery', Collection.dbquery, mysql_length=20)


class Collectionname(db.Model):

    """Represent a Collectionname record."""

    __tablename__ = 'collectionname'

    id_collection = db.Column(db.MediumInteger(9, unsigned=True),
                              db.ForeignKey(Collection.id),
                              nullable=False, primary_key=True)
    ln = db.Column(db.Char(5), nullable=False, primary_key=True,
                   server_default='')
    type = db.Column(db.Char(3), nullable=False, primary_key=True,
                     server_default='sn')
    value = db.Column(db.String(255), nullable=False)

    @db.hybrid_property
    def ln_type(self):
        """Get ln type."""
        return (self.ln, self.type)

    @ln_type.setter
    def set_ln_type(self, value):
        """Set ln type."""
        (self.ln, self.type) = value


class Collectionboxname(db.Model):

    """Represent a Collectionboxname record."""

    __tablename__ = 'collectionboxname'

    TYPES = {
        'v': 'Focus on:',
        'r': 'Narrow by collection:',
        'l': 'Latest additions:',
    }

    id_collection = db.Column(db.MediumInteger(9, unsigned=True),
                              db.ForeignKey(Collection.id),
                              nullable=False, primary_key=True)
    ln = db.Column(db.Char(5), nullable=False, primary_key=True,
                   server_default='')
    type = db.Column(db.Char(3), nullable=False, primary_key=True,
                     server_default='r')
    value = db.Column(db.String(255), nullable=False)

    @db.hybrid_property
    def ln_type(self):
        return (self.ln, self.type)

    @ln_type.setter
    def set_ln_type(self, value):
        (self.ln, self.type) = value


class Collectiondetailedrecordpagetabs(db.Model):

    """Represent a Collectiondetailedrecordpagetabs record."""

    __tablename__ = 'collectiondetailedrecordpagetabs'
    id_collection = db.Column(db.MediumInteger(9, unsigned=True),
                              db.ForeignKey(Collection.id),
                              nullable=False, primary_key=True)
    tabs = db.Column(db.String(255), nullable=False,
                     server_default='')
    collection = db.relationship(Collection,
                                 backref='collectiondetailedrecordpagetabs')


class CollectionCollection(db.Model):

    """Represent a CollectionCollection record."""

    __tablename__ = 'collection_collection'
    id_dad = db.Column(db.MediumInteger(9, unsigned=True),
                       db.ForeignKey(Collection.id), primary_key=True)
    id_son = db.Column(db.MediumInteger(9, unsigned=True),
                       db.ForeignKey(Collection.id), primary_key=True)
    type = db.Column(db.Char(1), nullable=False,
                     server_default='r')
    score = db.Column(db.TinyInteger(4, unsigned=True), nullable=False,
                      server_default='0')
    son = db.relationship(Collection, primaryjoin=id_son == Collection.id,
                          backref='dads',
                          # FIX
                          # collection_class=db.attribute_mapped_collection('score'),
                          order_by=db.asc(score))
    dad = db.relationship(Collection, primaryjoin=id_dad == Collection.id,
                          backref='sons', order_by=db.asc(score))


class Example(db.Model):

    """Represent a Example record."""

    __tablename__ = 'example'
    id = db.Column(db.MediumInteger(9, unsigned=True), primary_key=True,
                   autoincrement=True)
    type = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text, nullable=False)


class CollectionExample(db.Model):

    """Represent a CollectionExample record."""

    __tablename__ = 'collection_example'
    id_collection = db.Column(db.MediumInteger(9, unsigned=True),
                              db.ForeignKey(Collection.id), primary_key=True)
    id_example = db.Column(db.MediumInteger(9, unsigned=True),
                           db.ForeignKey(Example.id), primary_key=True)
    score = db.Column(db.TinyInteger(4, unsigned=True), nullable=False,
                      server_default='0')
    collection = db.relationship(Collection, backref='_examples',
                                 order_by=score)
    example = db.relationship(Example, backref='collections', order_by=score)


class Portalbox(db.Model):

    """Represent a Portalbox record."""

    __tablename__ = 'portalbox'
    id = db.Column(db.MediumInteger(9, unsigned=True), autoincrement=True,
                   primary_key=True)
    title = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text, nullable=False)


def get_pbx_pos():
    """Return a list of all the positions for a portalbox."""
    position = {}
    position["rt"] = "Right Top"
    position["lt"] = "Left Top"
    position["te"] = "Title Epilog"
    position["tp"] = "Title Prolog"
    position["ne"] = "Narrow by coll epilog"
    position["np"] = "Narrow by coll prolog"
    return position


class CollectionPortalbox(db.Model):

    """Represent a CollectionPortalbox record."""

    __tablename__ = 'collection_portalbox'
    id_collection = db.Column(db.MediumInteger(9, unsigned=True),
                              db.ForeignKey(Collection.id), primary_key=True)
    id_portalbox = db.Column(db.MediumInteger(9, unsigned=True),
                             db.ForeignKey(Portalbox.id), primary_key=True)
    ln = db.Column(db.Char(5), primary_key=True, server_default='',
                   nullable=False)
    position = db.Column(db.Char(3), nullable=False,
                         server_default='top')
    score = db.Column(db.TinyInteger(4, unsigned=True),
                      nullable=False,
                      server_default='0')
    collection = db.relationship(Collection, backref='portalboxes',
                                 order_by=score)
    portalbox = db.relationship(Portalbox, backref='collections',
                                order_by=score)


class CollectionFormat(db.Model):

    """Represent a CollectionFormat record."""

    __tablename__ = 'collection_format'
    id_collection = db.Column(db.MediumInteger(9, unsigned=True),
                              db.ForeignKey(Collection.id), primary_key=True)
    format_code = db.Column('format', db.String(10), primary_key=True)
    score = db.Column(db.TinyInteger(4, unsigned=True),
                      nullable=False, server_default='0')

    collection = db.relationship(
        Collection, backref=db.backref(
            'formats', order_by=db.desc(score)
        ), order_by=db.desc(score))

    @property
    def format(self):
        """Return output format definition."""
        return output_formats[self.format_code]


class FacetCollection(db.Model):

    """Facet configuration for collection."""

    __tablename__ = 'facet_collection'

    id = db.Column(db.Integer, primary_key=True)
    id_collection = db.Column(db.MediumInteger(9, unsigned=True),
                              db.ForeignKey(Collection.id))
    order = db.Column(db.Integer)
    facet_name = db.Column(db.String(80))

    collection = db.relationship(Collection, backref='facets')

    def __repr__(self):
        """Return class representation."""
        return ('FacetCollection <id: {0.id}, id_collection: '
                '{0.id_collection}, order: {0.order}, '
                'facet_name: {0.facet_name}>'.format(self))

    @classmethod
    def is_place_taken(cls, id_collection, order):
        """Check if there is already a facet on the given position.

        .. note:: This works well as a pre-check, however saving can still fail
            if somebody else creates the same record in other session
            (phantom reads).
        """
        return bool(cls.query.filter(
            cls.id_collection == id_collection,
            cls.order == order).count())

    @classmethod
    def is_duplicated(cls, id_collection, facet_name):
        """Check if the given facet is already assigned to this collection.

        .. note:: This works well as a pre-check, however saving can still fail
            if somebody else creates the same record in other session
            (phantom reads).
        """
        return bool(cls.query.filter(
            cls.id_collection == id_collection,
            cls.facet_name == facet_name).count())


__all__ = (
    'Collection',
    'Collectionname',
    'Collectiondetailedrecordpagetabs',
    'CollectionCollection',
    'Example',
    'CollectionExample',
    'Portalbox',
    'CollectionPortalbox',
    'CollectionFormat',
    'FacetCollection',
)
