/*
Copyright 2017 Rice University

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/
package edu.rice.cs.caper.bayou.core.dom_driver;


import edu.rice.cs.caper.bayou.core.dsl.DLoop;
import edu.rice.cs.caper.bayou.core.dsl.DSubTree;
import org.eclipse.jdt.core.dom.Expression;
import org.eclipse.jdt.core.dom.ForStatement;

public class DOMForStatement implements Handler {

    final ForStatement statement;
    final Visitor visitor;

    public DOMForStatement(ForStatement statement, Visitor visitor) {
        this.statement = statement;
        this.visitor = visitor;
    }

    @Override
    public DSubTree handle() {
        DSubTree tree = new DSubTree();

        for (Object o : statement.initializers()) {
            DSubTree init = new DOMExpression((Expression) o, visitor).handle();
            tree.addNodes(init.getNodes());
        }
        DSubTree cond = new DOMExpression(statement.getExpression(), visitor).handle();
        DSubTree body = new DOMStatement(statement.getBody(), visitor).handle();
        for (Object o : statement.updaters()) {
            DSubTree update = new DOMExpression((Expression) o, visitor).handle();
            body.addNodes(update.getNodes()); // updaters are part of body
        }

        boolean loop = cond.isValid();

        if (loop)
            tree.addNode(new DLoop(cond.getNodesAsCalls(), body.getNodes()));
        else {
            // only one of these will add nodes
            tree.addNodes(cond.getNodes());
            tree.addNodes(body.getNodes());
        }

        return tree;
    }
}
