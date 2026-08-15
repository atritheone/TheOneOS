solutions = [
  { "name"        : 'src',
    "url"         : 'https://github.com/chromium/chromium.git',
    "deps_file"   : 'DEPS',
    "managed"     : False,
    "custom_deps" : {
    },
    "custom_vars": {'checkout_pgo_profiles': True},
  },
]
