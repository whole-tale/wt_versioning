import router from 'girder/router';
import events from 'girder/events';
import { exposePluginConfig } from 'girder/utilities/PluginUtils';

import ConfigView from './views/ConfigView';

exposePluginConfig('wt_versioning', 'plugins/wt_versioning/config');

router.route('plugins/wt_versioning/config', 'versioningConfig', function () {
    events.trigger('g:navigateTo', ConfigView);
});
