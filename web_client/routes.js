import router from 'girder/router';
import events from 'girder/events';
import { exposePluginConfig } from 'girder/utilities/PluginUtils';

exposePluginConfig('wt_versioning', 'plugins/wt_versioning/config');

import ConfigView from './views/ConfigView';
router.route('plugins/wt_versioning/config', 'VersioningConfig', function () {
    events.trigger('g:navigateTo', ConfigView);
});
