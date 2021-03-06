from collections import namedtuple
import logging

from django.core.urlresolvers import reverse
from django.conf.urls import patterns, url
from django.contrib.auth import models as auth_app
from django.db.models import get_models, signals

import extra_views

from . import apiviews
from . import settings
from . import views
from . import actions
from . import utils
from .forms import modelform_factory

logger = logging.getLogger(__name__)


class ModelAdmin2(object):
    """
    Warning: This class is targeted for reduction.
                It's bloated and ugly.
    """

    list_display = ('__str__',)
    list_display_links = ()
    list_filter = ()
    list_select_related = False
    list_per_page = 100
    list_max_show_all = 200
    list_editable = ()
    search_fields = ()
    save_as = False
    save_on_top = False
    verbose_name = None
    verbose_name_plural = None
    model_admin_attributes = settings.MODEL_ADMIN_ATTRS

    search_fields = []

    # Show the fields to be displayed as columns
    # TODO: Confirm that this is what the Django admin uses
    list_fields = []

    #This shows up on the DocumentListView of the Posts
    list_actions = [actions.DeleteSelectedAction]

    # This shows up in the DocumentDetailView of the Posts.
    document_actions = []

    # shows up on a particular field
    field_actions = {}

    fields = None
    exclude = None
    fieldsets = None
    form_class = None
    filter_vertical = ()
    filter_horizontal = ()
    radio_fields = {}
    prepopulated_fields = {}
    formfield_overrides = {}
    readonly_fields = ()
    ordering = None

    create_form_class = None
    update_form_class = None

    inlines = []

    #  Views
    index_view = views.ModelListView
    create_view = views.ModelAddFormView
    update_view = views.ModelEditFormView
    detail_view = views.ModelDetailView
    delete_view = views.ModelDeleteView

    # API configuration
    api_serializer_class = None

    # API Views
    api_list_view = apiviews.ListCreateAPIView
    api_detail_view = apiviews.RetrieveUpdateDestroyAPIView

    def __init__(self, model, admin, name=None, **kwargs):
        self.name = name
        self.model = model
        self.admin = admin
        model_options = utils.model_options(model)
        self.app_label = model_options.app_label
        self.model_name = model_options.object_name.lower()

        if self.name is None:
            self.name = '{}_{}'.format(self.app_label, self.model_name)

        if self.verbose_name is None:
            self.verbose_name = model_options.verbose_name
        if self.verbose_name_plural is None:
            self.verbose_name_plural = model_options.verbose_name_plural

    def get_default_view_kwargs(self):
        return {
            'app_label': self.app_label,
            'model': self.model,
            'model_name': self.model_name,
            'model_admin': immutable_admin_factory(self),
        }

    def get_default_api_view_kwargs(self):
        kwargs = self.get_default_view_kwargs()
        kwargs.update({
            'serializer_class': self.api_serializer_class,
        })
        return kwargs

    def get_prefixed_view_name(self, view_name):
        return '{}_{}'.format(self.name, view_name)

    def get_index_kwargs(self):
        return self.get_default_view_kwargs()

    def get_create_kwargs(self):
        kwargs = self.get_default_view_kwargs()
        kwargs.update({
            'inlines': self.inlines,
            'form_class': self.create_form_class if self.create_form_class else self.form_class,
        })
        return kwargs

    def get_update_kwargs(self):
        kwargs = self.get_default_view_kwargs()
        form_class = self.update_form_class if self.update_form_class else self.form_class
        if form_class is None:
            form_class = modelform_factory(self.model)
        kwargs.update({
            'inlines': self.inlines,
            'form_class': form_class,
        })
        return kwargs

    def get_detail_kwargs(self):
        return self.get_default_view_kwargs()

    def get_delete_kwargs(self):
        return self.get_default_view_kwargs()

    def get_index_url(self):
        return reverse('admin2:{}'.format(self.get_prefixed_view_name('index')))

    def get_api_list_kwargs(self):
        kwargs = self.get_default_api_view_kwargs()
        kwargs.update({
            'paginate_by': self.list_per_page,
        })
        return kwargs

    def get_api_detail_kwargs(self):
        return self.get_default_api_view_kwargs()

    def get_urls(self):
        return patterns('',
            url(
                regex=r'^$',
                view=self.index_view.as_view(**self.get_index_kwargs()),
                name=self.get_prefixed_view_name('index')
            ),
            url(
                regex=r'^create/$',
                view=self.create_view.as_view(**self.get_create_kwargs()),
                name=self.get_prefixed_view_name('create')
            ),
            url(
                regex=r'^(?P<pk>[0-9]+)/$',
                view=self.detail_view.as_view(**self.get_detail_kwargs()),
                name=self.get_prefixed_view_name('detail')
            ),
            url(
                regex=r'^(?P<pk>[0-9]+)/update/$',
                view=self.update_view.as_view(**self.get_update_kwargs()),
                name=self.get_prefixed_view_name('update')
            ),
            url(
                regex=r'^(?P<pk>[0-9]+)/delete/$',
                view=self.delete_view.as_view(**self.get_delete_kwargs()),
                name=self.get_prefixed_view_name('delete')
            ),
        )

    def get_api_urls(self):
        return patterns('',
            url(
                regex=r'^$',
                view=self.api_list_view.as_view(**self.get_api_list_kwargs()),
                name=self.get_prefixed_view_name('api_list'),
            ),
            url(
                regex=r'^(?P<pk>[0-9]+)/$',
                view=self.api_detail_view.as_view(**self.get_api_detail_kwargs()),
                name=self.get_prefixed_view_name('api_detail'),
            ),
        )

    @property
    def urls(self):
        # We set the application and instance namespace here
        return self.get_urls(), None, None

    @property
    def api_urls(self):
        return self.get_api_urls(), None, None

    def get_list_actions(self):
        actions_dict = {}

        for cls in type(self).mro()[::-1]:
            class_actions = getattr(cls, 'list_actions', [])
            for action in class_actions:
                actions_dict[action.__name__] = {
                        'name': action.__name__,
                        'description': actions.get_description(action),
                        'action_class': action
                }
        return actions_dict


class Admin2Inline(extra_views.InlineFormSet):
    """
    A simple extension of django-extra-view's InlineFormSet that
    adds some useful functionality.
    """

    def construct_formset(self):
        """
        Overrides construct_formset to attach the model class as
        an attribute of the returned formset instance.
        """
        formset = super(Admin2Inline, self).construct_formset()
        formset.model = self.inline_model
        return formset


def create_extra_permissions(app, created_models, verbosity, **kwargs):
    """
    Creates 'view' permissions for all models.
    django.contrib.auth only creates add, change and delete permissions. Since we also support read-only views, we need
    to add our own extra permission.
    Copied from django.contrib.auth.management.create_permissions

    # TODO - determine if this is deprecated by the new permissions.py module
    """
    # Is there any reason for doing this import here?
    from django.contrib.contenttypes.models import ContentType

    app_models = get_models(app)

    # This will hold the permissions we're looking for as
    # (content_type, (codename, name))
    searched_perms = list()
    # The codenames and ctypes that should exist.
    ctypes = set()
    for klass in app_models:
        ctype = ContentType.objects.get_for_model(klass)
        ctypes.add(ctype)

        opts = utils.model_options(klass)
        perm = ('view_%s' % opts.object_name.lower(), u'Can view %s' % opts.verbose_name_raw)
        searched_perms.append((ctype, perm))

    # Find all the Permissions that have a content_type for a model we're
    # looking for.  We don't need to check for codenames since we already have
    # a list of the ones we're going to create.
    all_perms = set(auth_app.Permission.objects.filter(
        content_type__in=ctypes,
    ).values_list(
        "content_type", "codename"
    ))

    perms = [
        auth_app.Permission(codename=codename, name=name, content_type=ctype)
        for ctype, (codename, name) in searched_perms
        if (ctype.pk, codename) not in all_perms
    ]
    auth_app.Permission.objects.bulk_create(perms)
    if verbosity >= 2:
        for perm in perms:
            logger.debug("Adding permission '%s'" % perm)


signals.post_syncdb.connect(create_extra_permissions,
    dispatch_uid="django-admin2.djadmin2.models.create_extra_permissions")


def immutable_admin_factory(model_admin):
    """ Provide an ImmutableAdmin to make it harder for developers to dig themselves into holes.
        See https://github.com/twoscoops/django-admin2/issues/99
        Frozen class implementation as namedtuple suggested by Audrey Roy

        Note: This won't stop developers from saving mutable objects to the result, but hopefully
                developers attempting that 'workaround/hack' will read our documentation.
    """
    ImmutableAdmin = namedtuple("ImmutableAdmin", model_admin.model_admin_attributes, verbose=False)
    return ImmutableAdmin(*[getattr(model_admin, x) for x in model_admin.model_admin_attributes])

