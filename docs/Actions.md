These are the actions that can be added to Controllers (i.e. Input, Conditional, and Trigger Controllers) to provide a way to add additional functionality or interact with other parts of AoT. Actions may work with one or more controller type, depending on how the Action has been designed.

For a full list of supported Actions, see [Supported Actions](Supported-Actions.md).

## Custom Actions

There is a Custom Action import system in AoT that allows user-created Actions to be used in the AoT system. Custom Actions can be uploaded on the `[Gear Icon] -> Configure -> Custom Actions` page. After import, they will be available to use on the `Setup -> Function` page.

If you develop a working Action module, please consider [creating a new GitHub issue](https://github.com/aot-inc/AoT/issues/new?assignees=&labels=&template=feature-request.md&title=New%20Module) or pull request, and it may be included in the built-in set.

Open any of the built-in modules located in the directory [AoT/aot/actions](https://github.com/aot-inc/AoT/tree/master/aot/actions/) for examples of the proper formatting.

There are also example Custom Actions in the directory [AoT/aot/actions/examples](https://github.com/aot-inc/AoT/tree/master/aot/actions/examples)

Additionally, I have another github repository devoted to Custom Modules that are not included in the built-in set, at [aot-inc/AoT-custom](https://github.com/aot-inc/AoT-custom).
