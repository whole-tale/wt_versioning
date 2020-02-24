get_filename_component(PLUGIN ${CMAKE_CURRENT_LIST_DIR} NAME)

add_eslint_test(${PLUGIN}
    "${PROJECT_SOURCE_DIR}/plugins/${PLUGIN}/web_client")
add_puglint_test(${PLUGIN}
    "${PROJECT_SOURCE_DIR}/plugins/${PLUGIN}/web_client/templates")

add_python_test(
  wt_versioning
  PLUGIN ${PLUGIN}
)

add_python_style_test(
  python_static_analysis_${PLUGIN}
  "${PROJECT_SOURCE_DIR}/plugins/${PLUGIN}/server"
)
add_python_style_test(
  python_static_analysis_${PLUGIN}_tests
  "${PROJECT_SOURCE_DIR}/plugins/${PLUGIN}/plugin_tests"
)
